# 챗봇/PDF 인용 → 클릭 → 연관 판례 그래프 (프론트 연동 가이드)

이 문서는 **챗봇 답변**과 **PDF 문서 검토 finding**의 인용을 클릭 가능하게 렌더하고,
클릭 시 `/v1/related-graph`(연관 판례 그래프)를 호출해 마인드맵으로 그리는 프론트 연동 방법을 설명한다.

모든 스키마/필드명은 `app/schemas.py`의 실제 정의를 따른다(추측 없음).

---

## 1. 전체 흐름도

```
[챗봇 /chat · /chat/stream]              [PDF /documents/review]
   answer + answer_segments[]               findings[].citations[]
   sources[] (ChatSource)                   (이미 구조화된 ChatSource)
        │                                         │
        ▼                                         ▼
   answer_segments 순회                      finding 카드 렌더
   - type:"text" → 그냥 텍스트                citations[] 칩을
   - type:"cite" → 클릭 가능 칩               클릭 가능하게 렌더
        │                                         │
        └──────────────┬──────────────────────────┘
                       ▼
          사용자가 인용([n] 또는 finding 칩) 클릭
                       ▼
        클릭 대상의 {source_type, source_id} → seeds[]
        보고 있던 문구/질의 → text
                       ▼
          POST /v1/related-graph (RelatedGraphRequest)
                       ▼
        RelatedGraphResponse: root → issues[] → cases[]/sanctions[]
                       ▼
          노드/엣지로 변환해 마인드맵 렌더
          (highlighted / statute_highlighted = 강조)
```

**호출 구조(서버-서버 중계):** 브라우저(React)는 API 키를 직접 들고 있지 않는다.
`React → Node(BFF) → FastAPI` 로 중계한다. Node 서버가 `X-API-Key`(또는 `require_api_key`가 받는 헤더)를
붙여 FastAPI를 호출하고, 응답 JSON을 그대로 React에 돌려준다. 아래 예제의 `fetch('/api/...')`는 Node BFF 엔드포인트를 가리킨다.

---

## 2. 챗봇 응답 렌더 (`/chat`)

`ChatResponse.answer_segments`는 `answer` 문자열을 `[n]` 기준으로 쪼갠 렌더용 배열이다.
각 원소는 `AnswerSegment`:

| 필드 | 타입 | 의미 |
|---|---|---|
| `type` | `"text"` \| `"cite"` | text=일반 본문, cite=클릭 가능한 인용 토큰 |
| `text` | string | text 본문 / cite면 표시 라벨(예: `"[1]"`) |
| `n` | int \| null | cite일 때 인용 번호 |
| `source_type` | SourceType \| null | cite seed용 |
| `source_id` | int \| null | cite seed용 |
| `label` | string | cite 라벨(예: `"의료법 제27조"`) |

> SourceType = `"statute" | "case" | "interpretation" | "decision" | "guideline"`

```js
// answer_segments[] → DOM. cite 토큰만 클릭 가능하게.
function renderAnswer(container, resp) {
  container.replaceChildren();
  for (const seg of resp.answer_segments) {
    if (seg.type === "cite") {
      const a = document.createElement("button");
      a.className = "cite";
      a.textContent = seg.text;                 // 예: "[1]"
      a.title = seg.label;                      // 예: "의료법 제27조"
      a.onclick = () =>
        openRelatedGraph(
          [{ source_type: seg.source_type, source_id: seg.source_id }],
          resp.search_query || ""               // 보고 있던 질의
        );
      container.appendChild(a);
    } else {
      container.appendChild(document.createTextNode(seg.text));
    }
  }
}
```

### 스트리밍(`/chat/stream`) 패턴

SSE 이벤트 순서는 `sources` → `token`(여러 개) → `done` 이다.
토큰 수신 중에는 **raw 텍스트**를 그대로 누적해 보여주고(아직 `[n]`이 클릭 불가),
`done` 이벤트의 `answer_segments`로 **통째 교체**해 클릭 가능하게 만든다.

```js
async function streamChat(body, onRaw, onDone) {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "", raw = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const frames = buf.split("\n\n");
    buf = frames.pop();                          // 미완성 프레임 보류
    for (const f of frames) {
      const line = f.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const ev = JSON.parse(line.slice(6));
      if (ev.type === "sources") { /* ev.sources: ChatSource[] */ }
      else if (ev.type === "token") { raw += ev.text; onRaw(raw); }     // 진행 중: raw 텍스트
      else if (ev.type === "done") onDone(ev);   // ev.answer_segments / ev.citation_check
      else if (ev.type === "error") throw new Error(ev.message);
    }
  }
}

// done에서 answer_segments로 교체 → renderAnswer({answer_segments, search_query})
```

> 주의: 스트림의 `done` 이벤트에는 `answer_segments`, `citation_check`만 들어온다.
> `search_query`/`sources`는 앞선 `sources` 이벤트에서 받아 둔다.

---

## 3. PDF finding 렌더 (`/documents/review`)

`ReviewResponse.findings[]`는 각각 `ReviewFinding`이고, `citations` 필드가
**이미 구조화된 `ChatSource` 배열**이다. 텍스트 파싱이 전혀 필요 없다 — 칩에 클릭만 달면 된다.

`ReviewFinding` 주요 필드: `segment_index`, `segment_text`(before),
`risk_level`(`"high"|"medium"|"low"`), `issue`, `suggestion`(after), `citations: ChatSource[]`.

```js
// findings[] → 카드 + 각 citation을 클릭 가능한 칩으로.
function renderFindings(container, review) {
  container.replaceChildren();
  for (const f of review.findings) {
    const card = document.createElement("div");
    card.className = `finding risk-${f.risk_level}`;
    card.append(makeText(`⚠ ${f.issue}`), makeText(`원문: ${f.segment_text}`),
                makeText(`권고: ${f.suggestion}`));

    for (const c of f.citations) {               // ChatSource[]
      const chip = document.createElement("button");
      chip.className = "cite";
      chip.textContent = c.label;                 // 예: "의료법 제56조"
      chip.onclick = () =>
        openRelatedGraph(
          [{ source_type: c.source_type, source_id: c.source_id }],
          f.segment_text                          // 보고 있던 문구 = 위험 세그먼트
        );
      card.appendChild(chip);
    }
    container.appendChild(card);
  }
}
function makeText(t) { const p = document.createElement("p"); p.textContent = t; return p; }
```

---

## 4. 클릭 → seed 변환 + 그래프 호출

클릭 대상(cite 토큰 또는 ChatSource)의 `{ source_type, source_id }`를 그대로
`RelatedGraphRequest.seeds`에 넣는다. `text`에는 사용자가 **보고 있던 문구/질의**를 넣는다.

`RelatedGraphRequest`:

| 필드 | 타입 | 기본 | 의미 |
|---|---|---|---|
| `text` | string | (필수) | 보고 있던 문구/질의(광고 문구, 챗봇 질의 등) |
| `lang` | string | `"ko"` | 라벨 언어 `ko`\|`en` |
| `as_of` | string \| null | null | 시점 조회 `YYYY-MM-DD` |
| `top_k` | int(1~30) | 12 | 검색 후보 수 |
| `seeds` | `GraphSeed[]` | `[]` | 클릭한 인용. 그래프에 반드시 포함·강조 |

> `GraphSeed = { source_type: SourceType, source_id: int }`

```js
// 공용 진입점 — cite 토큰/finding 칩 양쪽에서 호출.
async function openRelatedGraph(seeds, text, opts = {}) {
  const res = await fetch("/api/related-graph", {      // Node BFF → FastAPI /v1/related-graph
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,                                            // 보고 있던 문구/질의
      seeds,                                           // [{source_type, source_id}, ...]
      lang: opts.lang || "ko",
      top_k: opts.top_k || 12,
      ...(opts.as_of ? { as_of: opts.as_of } : {}),
    }),
  });
  const graph = await res.json();                      // RelatedGraphResponse
  renderGraph(toGraph(graph));                         // §5 참고
}
```

---

## 5. 그래프 JSON → 노드/엣지 매핑

`RelatedGraphResponse`는 3층 구조다: `root → issues[] → cases[] / sanctions[]`.

```
RelatedGraphResponse
├─ root: { label, text }
├─ issues: GraphIssue[]
│    ├─ label                       (쟁점명)
│    ├─ statute                     (조문 라벨, 예 "의료법 제56조")
│    ├─ statute_highlighted: bool   (이 조문이 클릭한 seed면 true → 강조)
│    ├─ cases: GraphCase[]
│    │    ├─ source_id
│    │    ├─ label                  (예 "대법원 2018두12345")
│    │    ├─ title / summary / source_url
│    │    └─ highlighted: bool      (클릭한 seed 판례면 true → 강조)
│    └─ sanctions: string[]         (제재수위, 예 ["업무정지 1개월"])
├─ method: "hybrid" | "fts"
└─ llm: bool                        (false=규칙 폴백)
```

매핑 규칙:
- `root` → 루트 노드 1개.
- 각 `issue` → 쟁점 노드. `root → issue` 엣지.
- `issue.statute`가 있으면 조문 노드 + `issue → statute` 엣지. `statute_highlighted`면 강조 클래스.
- 각 `case` → 판례 노드 + `issue → case` 엣지. `highlighted`면 강조 클래스(클릭한 인용).
- `sanctions[]` → 판례 노드 라벨에 배지로 붙이거나 별도 작은 노드로. (issue 단위 제재이므로 issue에 붙여도 됨)

```js
// RelatedGraphResponse → { nodes, edges } (라이브러리 중립 형태)
function toGraph(resp) {
  const nodes = [], edges = [];
  const ROOT = "root";
  nodes.push({ id: ROOT, kind: "root", label: resp.root.label, text: resp.root.text });

  resp.issues.forEach((issue, i) => {
    const issueId = `issue-${i}`;
    nodes.push({ id: issueId, kind: "issue", label: issue.label, sanctions: issue.sanctions });
    edges.push({ from: ROOT, to: issueId });

    if (issue.statute) {
      const stId = `statute-${i}`;
      nodes.push({
        id: stId, kind: "statute", label: issue.statute,
        highlighted: issue.statute_highlighted,          // 클릭한 조문 강조
      });
      edges.push({ from: issueId, to: stId });
    }

    issue.cases.forEach((c, j) => {
      const caseId = `case-${i}-${j}`;
      nodes.push({
        id: caseId, kind: "case",
        label: c.label, title: c.title, summary: c.summary, url: c.source_url,
        highlighted: c.highlighted,                      // 클릭한 판례 강조
      });
      edges.push({ from: issueId, to: caseId });
    });
  });
  return { nodes, edges, llm: resp.llm, method: resp.method };
}
```

`renderGraph(graph)`는 마인드맵 라이브러리에 맞게 구현한다. 가볍게 추천(강요 아님):
**react-flow**, **cytoscape**, **vis-network** 중 하나. `kind`별로 색/모양을 다르게,
`highlighted`/`statute_highlighted` 노드는 테두리 강조 + 자동 포커스하면 좋다.

---

## 6. 요청/응답 예시 JSON (실제 필드명)

### 요청 — `POST /v1/related-graph`

```json
{
  "text": "전국에서 가장 안전한 시술, 부작용 0%",
  "lang": "ko",
  "top_k": 12,
  "seeds": [
    { "source_type": "statute", "source_id": 56 }
  ]
}
```

### 응답 — `RelatedGraphResponse`

```json
{
  "root": {
    "label": "입력 문구",
    "text": "전국에서 가장 안전한 시술, 부작용 0%"
  },
  "issues": [
    {
      "label": "과장·허위 의료광고",
      "statute": "의료법 제56조",
      "statute_highlighted": true,
      "cases": [
        {
          "source_id": 1234,
          "label": "대법원 2018두12345",
          "title": "의료광고 행정처분 취소",
          "summary": "부작용 가능성을 배제한 단정적 표현은 과장광고에 해당한다...",
          "source_url": "https://...",
          "highlighted": false
        }
      ],
      "sanctions": ["업무정지 1개월", "시정명령"]
    }
  ],
  "method": "hybrid",
  "llm": true
}
```

---

## 7. 주의 사항

- **`[n]` 매칭은 서버가 한다.** `answer`의 `[n]`은 `answer_segments`/`sources`의 `n`과 매칭된다.
  매칭 안 되는 `[n]`(환각·오번호)은 서버가 `answer_segments`에서 `type:"text"`로 **강등**한다.
  따라서 프론트는 `type === "cite"`인 토큰만 클릭 가능하게 그리면 되고, 직접 `[n]`을 정규식으로
  파싱하지 말 것(강등된 `[n]`은 클릭 불가가 정상).
- **스트리밍 중에는 클릭 불가.** `token` 단계의 raw 텍스트엔 seed가 없다. `done`의 `answer_segments`로
  교체된 뒤에야 cite 토큰이 클릭 가능해진다.
- **PDF finding은 파싱 불필요.** `findings[].citations`가 이미 `ChatSource`(`source_type`/`source_id` 포함)이므로
  그대로 seed로 쓴다.
- **`llm: false`면 규칙 폴백 그래프.** LLM 불가/실패/빈 결과 시 서버가 규칙 기반으로
  "관련 판례·근거" 단일 쟁점으로 묶어 graceful degrade 한다. 노드는 정상 렌더되지만 쟁점 분류가
  거칠 수 있으니, UI에서 "자동 분류(규칙)" 같은 표식을 줄 수 있다.
- **빈 그래프 가능성.** `text`도 없고 seed 복원도 실패하면 `issues: []`가 올 수 있다. 빈 상태 UI를 준비할 것.
- **seed는 반드시 포함·강조된다.** 검색 히트에 없던 seed도 서버가 복원해 그래프에 넣고
  `highlighted`/`statute_highlighted`로 표시한다. 클릭한 인용이 화면에서 강조되도록 그 플래그를 활용.
- **API 키는 노출 금지.** `require_api_key`가 필요한 호출은 Node BFF에서만 키를 붙인다(React 직접 호출 금지).
- **`lang`.** 영어 UI면 요청에 `lang:"en"`을 넣는다. 그래프 라벨(root.label, "클릭한 인용" 등)이 영어로 온다.

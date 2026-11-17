"""Decision Flow page. Owner: M4 (see CLAUDE.md).

Shows, step by step, how one question is answered: input guardrail -> router (route,
initiatives, metrics) -> scorecard lookup (governed values) and/or embedding retrieval
(charter chunks with hybrid scores) -> LLM draft -> output guardrail -> final answer.
Uses only the public functions in CLAUDE.md section 5; the page computes nothing.
"""
import logging

import streamlit as st

from src import config
from src.ai import answer as ai_answer
from src.ai import guardrails, router
from src.charters import retriever as charter_retriever
from src.contracts import Evidence, RouteDecision
from src.report.weekly import format_metric
from src.scorecard import store as scorecard_store

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Decision Flow", layout="wide")
st.title("Decision Flow")
st.caption("See which path a question takes: the route, the scorecard values and the charter "
           "(embedding) context that ground the answer.")

EXAMPLES = [
    "What is the adoption rate of PHIS?",
    "What is the latest CIO risk rating for ATS and what did the CIO say?",
    "Why does EPS need attention and what risks does its charter record?",
    "What will the portfolio ROI be next year?",
    "What is the email address of Meera Sethi?",
]
ON, OFF = "#2e7d32", "#bdbdbd"


def flow_chart(stage: str, decision: RouteDecision | None, final_status: str | None) -> str:
    """Graphviz DOT for the pipeline with the path this question took highlighted."""
    taken: set[str] = {"q", "in"}
    if stage == "refused":
        taken |= {"refuse"}
    elif decision is not None:
        taken |= {"route"}
        if decision.route == "out_of_scope":
            taken |= {"oos"}
        else:
            if decision.route in ("numeric", "mixed"):
                taken |= {"sc"}
            if decision.route in ("narrative", "mixed"):
                taken |= {"emb"}
            taken |= {"llm", "out"}
        if final_status:
            taken |= {"ans" if final_status == "answered" else "fb"}
    labels = {
        "q": "Question", "in": "Input guardrail\n(personal data)", "refuse": "Refused",
        "route": f"Router\n{decision.route if decision else ''}", "oos": "Out of scope",
        "sc": "Scorecard lookup\n(SQLite, M1)", "emb": f"Charter retrieval\n({config.EMBEDDING_MODEL})",
        "llm": "LLM draft\n(evidence only)", "out": "Output guardrail\n(numbers, citations)",
        "ans": "Answer with sources", "fb": "I do not have that\nin the data provided.",
    }
    edges = [("q", "in"), ("in", "refuse"), ("in", "route"), ("route", "oos"), ("route", "sc"),
             ("route", "emb"), ("sc", "llm"), ("emb", "llm"), ("llm", "out"), ("out", "ans"),
             ("out", "fb"), ("oos", "fb")]
    lines = ["digraph G {", "rankdir=LR;", 'node [shape=box, style="rounded,filled", fontname="Helvetica"];']
    for key, text in labels.items():
        on = key in taken
        lines.append(f'{key} [label="{text}", fillcolor="{"#e8f5e9" if on else "#fafafa"}", '
                     f'color="{ON if on else OFF}", fontcolor="{"black" if on else "#9e9e9e"}"];')
    for a, b in edges:
        on = a in taken and b in taken
        lines.append(f'{a} -> {b} [color="{ON if on else OFF}", penwidth={2.5 if on else 1}];')
    lines.append("}")
    return "\n".join(lines)


def safe(fn, *args) -> list[Evidence]:
    """Call another member's public function; [] when it is unavailable."""
    try:
        return fn(*args)
    except NotImplementedError:
        return []
    except Exception:
        logger.exception("%s failed", getattr(fn, "__name__", "call"))
        return []


def known_ids() -> list[str]:
    """Initiative IDs from the governed scorecard ([] if not built)."""
    try:
        return [r.initiative_id for r in scorecard_store.load_scorecard(config.DB_PATH)]
    except Exception:
        return []


cols = st.columns(len(EXAMPLES))
clicked = next((q for col, q in zip(cols, EXAMPLES) if col.button(q, width="stretch")), None)
typed = st.text_input("Question", value=clicked or st.session_state.get("flow_q", ""))
question = (clicked or typed or "").strip()
if not question:
    st.graphviz_chart(flow_chart("idle", None, None))
    st.stop()
st.session_state.flow_q = question

refusal = guardrails.check_input(question)
decision = None if refusal else router.route(question, known_ids())
final = refusal or ai_answer.answer_question(question)

st.graphviz_chart(flow_chart("refused" if refusal else "routed", decision, final.status))

st.subheader("1 · Input guardrail")
if refusal:
    st.warning(f"Refused before routing: {refusal.text}")
    st.stop()
st.success("Passed: no request for personal details.")

st.subheader("2 · Router")
c1, c2, c3 = st.columns(3)
c1.metric("Route", decision.route)
c2.metric("Initiatives", ", ".join(decision.initiative_ids) or "all")
c3.metric("Metrics", ", ".join(decision.metrics) or "none")
st.caption(f"Reason: {decision.reason}")

if decision.route == "out_of_scope":
    st.info("Out of scope: forecasts, what-ifs and ad-hoc aggregates are not in the governed data, "
            "so no evidence is fetched and no LLM is called.")
else:
    left, right = st.columns(2)
    with left:
        st.subheader("3a · Scorecard (governed values)")
        if decision.route in ("numeric", "mixed"):
            sc = safe(scorecard_store.lookup, decision.initiative_ids, decision.metrics, config.DB_PATH)
            if sc:
                st.dataframe([{"Evidence": e.evidence_id, "Initiative": e.initiative_id, "Metric": e.metric,
                               "Value": format_metric(e.metric or "", e.value)} for e in sc],
                             width="stretch", hide_index=True)
            else:
                st.caption("No scorecard values found (build the data on the home page).")
        else:
            st.caption("Not used: narrative questions are answered from the charters.")
    with right:
        st.subheader("3b · Embedding context (charters)")
        if decision.route in ("narrative", "mixed"):
            st.caption(f"Embedding model `{config.EMBEDDING_MODEL}` · top {config.TOP_K} chunks · "
                       f"minimum score {config.MIN_RETRIEVAL_SCORE}")
            ch = safe(charter_retriever.retrieve, question, decision.initiative_ids or None, config.TOP_K)
            if not ch:
                st.caption("No charter chunk passed the relevance threshold.")
            for e in ch:
                with st.expander(f"{e.evidence_id} · {e.section or ''} · score "
                                 f"{e.score:.2f}" if e.score is not None else e.evidence_id):
                    st.caption(e.source_file)
                    st.text(e.text[:800])
        else:
            st.caption("Not used: numeric questions are answered from the scorecard only.")

st.subheader("4 · LLM draft and output guardrail")
provider = ("Gemini" if config.get_secret("GEMINI_API_KEY") else
            "Sarvam" if config.get_secret("SARVAM_API_KEY") else "offline extractive fallback (no API key)")
st.caption(f"LLM: {provider} · temperature {config.LLM_TEMPERATURE} · the guardrail removes any number "
           "not in scorecard evidence and any uncited answer.")

st.subheader("5 · Final answer")
if final.status == "answered":
    st.write(final.text)
    for c in final.citations:
        st.markdown(f"- `{c.evidence_id}`: {c.claim}")
else:
    st.info(final.text or config.FALLBACK_TEXT)
st.caption(f"Status: {final.status} · route: {final.route or '-'}")

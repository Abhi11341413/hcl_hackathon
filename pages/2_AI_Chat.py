"""AI Chat page. Owner: M4 (see CLAUDE.md).

Sends questions to M3 answer_question and shows the answer with its sources.
The page never edits answer text or numbers; it only displays the approved Answer.
"""
import logging

import streamlit as st

from src import config
from src.ai import answer as ai_answer
from src.contracts import Answer

logger = logging.getLogger(__name__)

st.set_page_config(page_title="AI Chat", layout="wide")
st.title("AI Chat")
st.caption("Numeric questions use the governed scorecard; narrative questions use the charters; mixed questions use both.")

EXAMPLES = [
    "Which initiatives are Red?",
    "What is the adoption rate of EPS?",
    "What are the main risks recorded for ATS?",
    "Why does EPS need attention and what risks does its charter record?",
]
STATUS_BADGE = {"answered": "✅ Answered", "insufficient_evidence": "ℹ️ No evidence", "refused": "⛔ Refused"}


def ask(question: str) -> Answer | None:
    """Call the M3 pipeline. None means the pipeline is not implemented yet; any other
    failure becomes the standard no-evidence answer."""
    try:
        return ai_answer.answer_question(question)
    except NotImplementedError:
        return None
    except Exception:
        logger.exception("answer_question failed")
        return Answer(status="insufficient_evidence", text=config.FALLBACK_TEXT)


def show(ans: Answer) -> None:
    """Render one answer with its route, citations and evidence."""
    if ans.status == "insufficient_evidence":
        st.info(config.FALLBACK_TEXT)
    elif ans.status == "refused":
        st.warning(ans.text or config.REFUSAL_PII_TEXT)
    else:
        st.write(ans.text)
    meta = STATUS_BADGE.get(ans.status, ans.status)
    st.caption(f"{meta}" + (f" · route: {ans.route}" if ans.route else ""))
    if ans.citations:
        st.markdown("**Citations**")
        for c in ans.citations:
            st.markdown(f"- `{c.evidence_id}`: {c.claim}")
    if ans.evidence:
        with st.expander(f"Sources ({len(ans.evidence)})"):
            for ev in ans.evidence:
                where = f"{ev.source_file}" + (f" › {ev.section}" if ev.section else "")
                head = f"**[{ev.evidence_id}]** {ev.kind} · {ev.initiative_id} · {where}"
                st.markdown(head + (f" · score {ev.score:.2f}" if ev.score is not None else ""))
                st.text(ev.text[:600])


if "chat" not in st.session_state:
    st.session_state.chat = []

cols = st.columns(len(EXAMPLES))
pressed = [col.button(q, width="stretch") for col, q in zip(cols, EXAMPLES)]  # render all buttons every run
clicked = next((q for q, hit in zip(EXAMPLES, pressed) if hit), None)

for turn in st.session_state.chat:
    st.chat_message("user").write(turn["question"])
    with st.chat_message("assistant"):
        show(Answer.model_validate(turn["answer"]))

question = st.chat_input("Ask about adoption, value or initiatives needing attention") or clicked
if question and question.strip():
    st.chat_message("user").write(question)
    with st.chat_message("assistant"):
        with st.spinner("Finding evidence..."):
            answer = ask(question.strip())
        if answer is None:
            st.warning("The answer pipeline is not implemented yet (M3).")
        else:
            show(answer)
    if answer is not None:
        st.session_state.chat.append({"question": question, "answer": answer.model_dump(mode="json")})

if st.session_state.chat and st.button("Clear conversation"):
    st.session_state.chat = []
    st.rerun()

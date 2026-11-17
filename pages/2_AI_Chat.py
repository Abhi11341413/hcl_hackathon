"""AI Chat page. Owner: M4 (see CLAUDE.md).

Sends questions to M3 answer_question and shows the answer with its sources.
"""
import logging

import streamlit as st

from src.ai.answer import answer_question

logger = logging.getLogger(__name__)

st.title("AI Chat")
question = st.chat_input("Ask about adoption, value or initiatives needing attention")
if question:
    st.chat_message("user").write(question)
    try:
        ans = answer_question(question)
        with st.chat_message("assistant"):
            st.write(ans.text)
            if ans.evidence:
                with st.expander("Sources"):
                    for ev in ans.evidence:
                        st.write(f"[{ev.evidence_id}] {ev.source_file} {ev.section or ''}")
    except NotImplementedError:
        st.warning("Answer pipeline not implemented yet (M3).")

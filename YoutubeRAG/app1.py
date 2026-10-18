"""Legacy Streamlit demo entrypoint.

The production application now lives in the backend/ package plus the
Chrome extension. This file remains as a lightweight local demo that reuses
the same backend services.
"""

from __future__ import annotations

import streamlit as st

from backend.chat_service import answer_question, load_video_for_video_id
from backend.transcript_service import extract_video_id


st.set_page_config(page_title="YouTube Video Chatbot", page_icon="🎥", layout="wide")
st.title("🎥 YouTube Video Chatbot")
st.caption("Optional Streamlit demo that uses the same backend services as the Chrome extension.")

if "session_id" not in st.session_state:
    st.session_state.session_id = "streamlit-demo"

if "loaded_video_id" not in st.session_state:
    st.session_state.loaded_video_id = ""

video_url = st.text_input("Enter a YouTube video URL or video ID", value="https://www.youtube.com/watch?v=J5_-l7WIO_w")
question = st.text_area("Ask a question about the video", value="What is RAG?", height=100)

col1, col2 = st.columns(2)
load_clicked = col1.button("Load Video")
ask_clicked = col2.button("Ask")

if load_clicked:
    video_id = extract_video_id(video_url)
    if not video_id:
        st.error("Invalid YouTube URL or video ID.")
    else:
        result = load_video_for_video_id(video_id)
        if result.success:
            st.session_state.loaded_video_id = video_id
            st.success(f"Loaded {video_id}. Language: {result.language}. Translated: {result.translated}")
        else:
            st.error(result.message)

if ask_clicked:
    video_id = extract_video_id(video_url) or st.session_state.loaded_video_id
    if not video_id:
        st.error("Load a valid YouTube video first.")
    elif not question.strip():
        st.error("Ask a question first.")
    else:
        result = answer_question(video_id=video_id, question=question, session_id=st.session_state.session_id)
        if result.success:
            st.subheader("Answer")
            st.write(result.answer)
            if result.sources:
                st.subheader("Sources")
                for source in result.sources:
                    st.write(f"{source.start_time:.1f}s - {source.end_time:.1f}s")
        else:
            st.error(result.message)


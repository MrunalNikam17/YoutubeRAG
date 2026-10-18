# Evaluation

`dataset.json` contains five replaceable examples. Use real YouTube IDs with available captions and write questions whose expected answers are grounded in those captions. Each row must have this shape:

```json
{
  "video_id": "11-character YouTube ID",
  "question": "A question about the video",
  "expected_answer": "A concise reference answer",
  "type": "answerable"
}
```

Set `type` to `unanswerable` when the transcript does not contain the answer. For such rows, the runner requires the response to equal `I couldn't find that information in this video.` exactly. Keep answers specific and include names or numbers where applicable; these terms are also used to estimate retrieval hit rate from retrieved source excerpts.

The evaluation calls the real transcript/chat pipeline and Groq LLM-as-judge. Configure the backend environment, including `GROQ_API_KEY`, then run from the project root:

```powershell
python eval\run_eval.py --mode vector --rerank off
python eval\run_eval.py --mode hybrid --rerank on
```

`--mode` accepts `vector` or `hybrid`; `--rerank` accepts `on` or `off`. Results, including per-question judgments and errors, overwrite `eval/results.json`. Accuracy is the fraction graded fully correct, hallucination rate is the fraction of unanswerable rows that do not produce the exact fallback, and retrieval hit rate is the fraction of answerable rows with at least one non-stopword reference-answer term in returned source excerpts. Evaluation uses the same video transcript/cache pipeline as the application and requires network access on first load.

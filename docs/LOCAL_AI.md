# Optional local AI

Ollama is a separate local model runner, not bundled into the Git repository. Install it from [the official download page](https://ollama.com/download), start its service, then run:

```bash
ollama pull qwen2.5:0.5b
bash start.sh
```

In the dashboard: **Run live checks → Enable local AI for this session → Explain latest findings**. **Check Ollama** lists installed local models without loading them. AI is disabled on page reload. The model field is session-only; enter a different installed local model if desired. AI explanations are not stored in incident history.

For an existing Docker connection:

```bash
bash start.sh --tool docker diagnose --deep --ai
```

For another installed model:

```bash
bash start.sh diagnose --ai --ai-model qwen2.5:1.5b
```

Larger models need more RAM. The default [0.5B model](https://ollama.com/library/qwen2.5:0.5b) is approximately 398 MB to download; this is not its runtime RAM requirement. No fixed RAM minimum or production diagnosis accuracy is claimed. CPU responses may be slow. Settings request CPU inference, 2,048 context tokens, at most 384 output tokens and unloading after each response. Other Ollama clients may consume additional resources outside this assistant's control.

## Troubleshooting

| Problem | Action |
| --- | --- |
| Ollama unavailable | Start its service on the computer running the assistant. Use `ollama serve` if needed; an existing service may already occupy its port. |
| Model not installed | Run `ollama pull qwen2.5:0.5b`, then retry. The assistant never downloads models for you. |
| Request times out or memory is low | Close other model workloads or disable AI and use normal diagnosis. Socket operations time out after 90 seconds; timeout does not guarantee the Ollama process immediately stops inference. |
| Another AI request is running | Wait for that request to finish; the assistant permits one inference at a time per process. |
| Fresh checks requested | Run checks again for the currently selected target. Explanations require the latest matching incident. |
| Advice is generic or wrong | Review the original findings and runbooks. Small models and deliberately filtered evidence limit specificity. |
| Assistant runs inside a container | Loopback points inside that container. This version needs Ollama on the same loopback network; remote URLs and Docker host aliases are unsupported. |

## Boundaries and verification

Requests go directly to numeric loopback port 11434 using the [Ollama chat API](https://docs.ollama.com/api/chat). No endpoint override, proxy, redirect, API key, cloud model, shell execution, tool calling or AI-driven approval is supported. Do not replace the trusted local Ollama service with a remote relay. Initial Ollama/model downloads require internet; subsequent inference uses the installed local model.

The summary includes only finding codes, numeric disk/memory/load measurements, known log signature counts and collection/application flags. It omits raw evidence text, observed resource names, URLs, credentials and configuration. Normal repair approval and verification logic remain independent of model text. Output is advisory plain text; review it before any manual action.

Automated tests cover summary privacy, unavailable/missing models, cloud model exclusion, malformed/oversized responses, request serialization, CPU/context/unload options, authenticated dashboard requests, incident matching, diagnosis without AI and the local HTTP contract. No actual model inference or model answer quality was tested in this environment.


## Guided incident questions

The dashboard also supports six evidence-based topics without any model. After a live scan, choose a topic or type a short question. With AI enabled, **Also ask local AI** requests a separate explanation. The model receives the canonical topic rather than your raw text. Unsupported topics do not invoke AI. Demo questions never invoke Ollama. This is bounded guidance, not an autonomous investigation agent or unrestricted multi-turn LLM chat.

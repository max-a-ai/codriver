# Related work: what Codriver has to be different from

Reviewed 2026-09-14. Four systems, three retrieved, one blocked.

The short version: **natural-language control of ROS is a solved and
crowded problem, and speech is already in the closest prior system.**
Neither is available as a contribution. What is still open is the
combination of *acting*, *retrieval grounded in one specific vehicle's
own repository*, and *an action space bounded by what a human can click*.

---

## 1. ROSA — the Robot Operating System Agent (NASA JPL)

- arXiv [2410.06472](https://arxiv.org/abs/2410.06472), Oct 2024;
  published at IEEE Aerospace 2025.
- Code: [github.com/nasa-jpl/rosa](https://github.com/nasa-jpl/rosa)

An LLM agent, built on LangChain, that lets an operator inspect,
diagnose and operate a ROS system in natural language. Works with ROS 1
(Noetic+) and ROS 2 (Humble, Iron, Jazzy). The LLM reaches ROS through a
tool set — topics, services, parameters, diagnostics — and custom tools
can be added. Safety is "parameter validation and constraint
enforcement". Evaluated as "initial mock-up operations" in JPL's Mars
Yard, a lab, and simulation, across three robots; the abstract gives no
metrics.

**The part that hurts us:** the abstract explicitly claims *"multi-modal
capabilities such as speech integration and visual perception"*. Voice
control of a ROS robot is prior art, from a lab with the credibility of
JPL. We cannot claim it.

**Where it leaves room:** ROSA is a library and a REPL, not an operator
UI — you talk to it instead of looking at something. It introspects the
live ROS graph generically; it does not read the vehicle's *source
repository*, so it knows what topics exist but not why this rig was
built the way it was. And its action space is the ROS API, which is far
larger than anything a person would be given a button for.

## 2. ROSClaw — an OpenClaw ROS 2 framework for agentic robot control

- arXiv [2603.26997](https://arxiv.org/abs/2603.26997), Mar 2026.
- Cardenas, Arnett, Yeo, Sah, Kim.

A model-agnostic "executive layer" between a foundation model and ROS 2.
Dynamic capability discovery with standardised affordance injection,
multimodal observation normalisation, **pre-execution action validation
inside configurable safety parameters**, and structured audit logging.
Swapping the model or the robot is meant to be a configuration change.

Evaluated across three morphologies (wheeled, quadruped, humanoid) and
four foundation-model backends, reporting up to **4.8× differences in
out-of-policy action proposal rates between models**, and a
cross-framework parity protocol run against ROSA.

**The part that hurts us:** "the model may only do validated things" is
their contribution, done more rigorously than we planned, with numbers.
Our "MCP can only trigger what the UI offers" is the same idea unless we
say precisely how it differs.

**Where it leaves room:** their safety envelope is a configurable policy
the operator has to trust and cannot see. Ours is a screen the operator
is already looking at — the bound *is* the UI, so it is inspectable by
construction rather than by reading a config. That is a
human-factors argument, not a robotics one, which suits HCII.

Also: they set the evaluation bar. A cross-framework comparison against
ROSA now exists, so a new system that reports no comparison will look
thin.

## 3. ros2_rag (Aitor Ibarguren)

- [github.com/aitor-ibarguren/ros2_rag](https://github.com/aitor-ibarguren/ros2_rag)

A RAG system packaged as a **ROS 2 lifecycle node**. Local generation
via Hugging Face Transformers — Qwen (0.5B–72B) and DeepSeek-R1 distills
(1.5B–70B). FAISS with HNSW for semantic search, combined with
BM25-style keyword matching (hybrid retrieval). Corpus loaded from CSV
or PDF with configurable chunking. Hallucination reduction by
entailment checking with `cross-encoder/nli-deberta-v3-base`.
Conversation history with summarisation. Services:
`/ros2_rag/load_csv_data`, `/load_pdf_data`, `/save_index`, `/query`
(LLM only), `/rag_query` (with retrieved context). Docker image for ROS
2 Jazzy. No cloud dependency.

**The part that hurts us:** "small local LLM, RAG, inside ROS 2" is
already built and shipped. Local-and-private is not a contribution on
its own.

**Where it leaves room:** it **cannot act**. It is question-answering
only — no actuation, no control, no tools. And its corpus is whatever
CSV or PDF you hand it, which is the generic-documentation case, not
"this vehicle's own code".

## 4. SSRN 6856178 — NOT RETRIEVED

`papers.ssrn.com/sol3/papers.cfm?abstract_id=6856178` returns **HTTP 403**
to automated fetching, and the ID does not surface in web search. I have
no title, no authors and no abstract, so there is **nothing summarised
here and nothing I am willing to invent**.

**Needed from you:** the title and authors, or a PDF dropped into
`.docs/`. Until then this is a hole in the positioning, and if it is the
closest prior work the rest of this document may need revising.

---

## Where that leaves Codriver

| | ROSA | ROSClaw | ros2_rag | **Codriver** |
|---|---|---|---|---|
| Primary interface | agent/REPL | executive layer | ROS service | **a GUI** |
| Can act on the robot | yes | yes | **no** | yes |
| Retrieval | no | no | yes, CSV/PDF | **yes, the vehicle's repo** |
| Local model | optional | model-agnostic | yes | yes |
| Speech | **yes** | not stated | no | planned |
| Action space | ROS API | configurable policy | none | **exactly the UI's buttons** |
| Adapts to a new rig | live introspection | affordance discovery | n/a | **from a rosbag** |

Three claims survive contact with this literature:

1. **The UI is the contract, not a chat window.** In all three systems
   language is the interface. Here the panel is the artifact and language
   is a second channel onto the *same* actions. Nothing the model can do
   is invisible to somebody watching the screen, and every model action
   has a button that does the identical thing. This is the strongest
   card and it is an HCI claim, not a robotics one.
2. **Retrieval grounded in one vehicle's own repository.** Not general
   ROS documentation and not loose PDFs: the launch files, configs, URDF,
   scripts and notes of *this* rig, because every sensor-mounted vehicle
   is a one-off. ros2_rag has the machinery but points it at generic
   documents; ROSA and ROSClaw read the live graph but not the source.
3. **Automatic adaptation to a new sensor mount from a recording.**
   Deriving the panel — sensors, expected rates, topic groups — from a
   reference rosbag's `metadata.yaml` is the concrete mechanism behind
   claim 2, and I have not found it in any of the three.

Three claims **do not** survive, and should be dropped from the paper's
contribution list:

- *"Natural-language control of ROS."* Thoroughly done.
- *"Speech control of a robot."* ROSA claims speech integration.
- *"A small local LLM with RAG for robotics."* ros2_rag ships it.

They stay in the system as features. They are not contributions.

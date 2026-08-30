# Research: Inference Architecture & Cost Track
*Recovered from child agent transcript, 26 August 2026*

## DeepSeek-V3 Serving Requirements

- **Parameters:** 671B total (MoE), 37B active per token
- **Weights (bf16):** ~1,342 GB → needs ~17× A100-80GB
- **Weights (FP8):** ~671 GB → needs 8× H200-141GB (1,128GB total)
- **Weights (INT4):** ~336 GB → needs ~5× A100
- **Official inference:** torchrun --nnodes 2 --nproc-per-node 8 (16 GPUs)
- **SGLang:** Supports MLA, FP8 (W8A8), FP8 KV Cache, Torch Compile
- **CANNOT fit on 1× A100-80GB in any precision**
- Source: HuggingFace deepseek-ai/DeepSeek-V3 model card

## Llama-3.1-70B (docs' fallback)
- bf16: ~140 GB → does NOT fit on 1× A100-80GB
- INT4: ~35 GB → fits with tight KV-cache headroom

## Models that fit ONE 80GB GPU (Aug 2026)
- **gpt-oss-120b** (OpenAI, Aug 2025): 117B params, 5.1B active, MXFP4 quant, fits single H100/MI300X. Source: HuggingFace openai/gpt-oss-120b
- **Qwen3-32B**: fits comfortably
- **Llama-3.3-70B** (q4): fits with headroom
- **DeepSeek-V3.2-Exp**: FP8, 671B — still needs multi-GPU

## RunPod Pricing (Aug 2026, verified runpod.io/pricing)
- A100 PCIe 80GB: $1.39/hr (docs say $1.43 — outdated)
- A100 SXM 80GB: $1.59/hr
- H200 141GB: $4.59/hr
- H100 PCIe 80GB: $2.89/hr
- H100 SXM 80GB: $3.29/hr
- B300 288GB: $7.89/hr
- B200 180GB: $6.79/hr

8× H200 (minimum for DeepSeek-V3 FP8): ~$36.72/hr = ~A$41,400/mo

## API Pricing — OpenRouter (per 1M tokens, verified Aug 2026)

| Model | Input | Output |
|-------|-------|--------|
| deepseek-v4-flash | $0.04 | $0.08 |
| deepseek-v4-pro | $0.79 | $1.58 |
| deepseek-v3.2 | $0.26 | $0.38 |
| gpt-oss-120b | $0.037 | $0.17 |
| qwen3-32b | $0.08 | $0.28 |
| qwen3-235b-a22b | $0.45 | $1.82 |
| mistral-small-3.2-24b | $0.075 | $0.20 |

## AWS Bedrock Sydney (ap-southeast-2) — verified Aug 2026

### Available models in Sydney:
DeepSeek V3.1/V3.2, Claude Sonnet 5, Claude Opus 5, gpt-oss-120b, Qwen3-235B, Llama, Mistral, Kimi K2.5, NVIDIA Nemotron, Google Gemma, MiniMax, Z-AI GLM, OpenAI GPT, xAI

### Sydney pricing (per 1M tokens, Standard tier):
| Model | Input | Output |
|-------|-------|--------|
| DeepSeek V3.2 | $0.6386 | $1.9055 |
| DeepSeek V3.1 | $0.5974 | $1.7304 |
| gpt-oss-120b | $0.1545 | $0.618 |
| Qwen3-235B A22B 2507 | $0.2266 | $0.9064 |
| Claude Sonnet 5 | $2.00 | $10.00 |
| Claude Opus 5 | $5.00 | $25.00 |

### No-training guarantee:
- Bedrock: Customer data not used to train foundation models (AWS terms)
- Azure OpenAI: "are NOT used to train any generative AI foundation models without your permission or instruction" (Microsoft Foundry terms)
- Google Vertex: Standard Google Cloud data terms apply

### Data residency:
- Bedrock: ap-southeast-2 (Sydney) — data stays in region
- Azure: Australia East region
- Google: australia-southeast1 (Sydney)
- OpenAI: au.api.openai.com (Sydney endpoint, requires MAM or ZDR)

## Per-Case Token Accounting (9-turn, 3-agent debate + doc gen + citation checks)
- Input tokens: ~206,000
- Output tokens: ~32,200

## Per-Case COGS (AUD, at AUD≈1.55×USD)
| Model route | Per-case COGS (AUD) |
|-------------|-------------------|
| gpt-oss-120b (OpenRouter) | A$0.06 |
| DeepSeek V4 Flash (OpenRouter) | A$0.07 |
| Qwen3-32B (OpenRouter) | A$0.10 |
| DeepSeek V3.2 (Bedrock Sydney) | A$0.79 |
| gpt-oss-120b (Bedrock Sydney) | A$0.12 |
| Claude Sonnet 5 (Bedrock Sydney) | A$2.28 |
| Claude Opus 5 (Bedrock Sydney) | A$5.69 |

## Voice Pipeline Alternatives (Aug 2026)
- **TTS**: ElevenLabs (per-char pricing), AWS Polly (neural, AU region), OpenAI TTS, browser Web Speech API (free)
- **STT**: Deepgram ($0.0048–0.0077/min streaming), AssemblyAI ($0.15–0.21/hr), Whisper API, Deepgram Nova-3
- **Note**: REALTIME_COURTROOM.md VoiceControl component already uses browser SpeechSynthesis (free) — contradicts the paid ElevenLabs plan. The code and the pricing are inconsistent.
- **Recommendation**: Voice is not justified for MVP. Browser Web Speech API is free if needed. Paid TTS/STT is a Phase 3+ premium feature at best.

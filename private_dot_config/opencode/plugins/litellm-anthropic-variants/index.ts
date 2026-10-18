/**
 * opencode-plugin-litellm discovers reasoning-effort levels from the LiteLLM proxy and
 * registers each one as a variant with `{ reasoningEffort: <level> }`. That is the right
 * shape for OpenAI packages, but the Anthropic Messages packages ignore `reasoningEffort`:
 * they read `thinking` and `effort` (OpenCode's native catalog uses exactly this shape for
 * Claude 5.x). Without this rewrite every Claude variant on the `litellm-claude` provider
 * would silently run at the provider default.
 *
 * It also tags Claude models that do not come through GitHub Copilot with " (Vertex)" so
 * the two "Claude Opus 4.8" entries stay distinguishable in the model picker.
 *
 * Model transforms are replayed after every provider change, so the rewrite survives the
 * plugin's background discovery refreshes. Drop this plugin once opencode-plugin-litellm
 * emits package-aware variant settings itself.
 */
const PROVIDERS = new Set(["litellm-claude"])
const THINKING = { type: "adaptive", display: "summarized" }

// Per-model compatibility overrides for gateways whose Anthropic schema lags OpenCode's.
// Copilot rejects `thinking.adaptive.block_binding` for Opus 5.5 ("Extra inputs are not
// permitted") while accepting it for Fable 5.1 and Opus 4.8; OpenCode otherwise sends the
// field for every Claude >= 5.1. Verified 2026-10-18 with direct /v1/messages probes.
const COMPAT = {
  "litellm-claude/github_copilot/claude-opus-5.5": { supportsThinkingBlockBinding: false },
}

export default {
  id: "litellm-anthropic-variants",
  async setup(ctx) {
    await ctx.model.transform((editor) => {
      for (const model of editor.list()) {
        if (!PROVIDERS.has(model.providerID)) continue
        editor.update(model.providerID, model.id, (draft) => {
          if (!String(model.id).startsWith("github_copilot/") && !draft.name.endsWith("(Vertex)")) {
            draft.name = `${draft.name} (Vertex)`
          }
          const compat = COMPAT[`${model.providerID}/${model.id}`]
          if (compat) draft.compatibility = { ...(draft.compatibility ?? {}), ...compat }
          draft.variants = draft.variants.map((variant) => {
            const effort = variant.settings?.reasoningEffort
            if (typeof effort !== "string") return variant
            return { ...variant, settings: { thinking: { ...THINKING }, effort } }
          })
        })
      }
    })
  },
}

/**
 * Adds local display labels and gateway compatibility overrides for `litellm-claude`.
 * Reasoning-effort variants are handled by opencode-plugin-litellm itself as of 1.7.1.
 *
 * Tags Claude models that do not come through GitHub Copilot with " (Vertex)" so
 * the two "Claude Opus 4.8" entries stay distinguishable in the model picker.
 *
 * Model transforms are replayed after every provider change, so these customizations
 * survive the plugin's background discovery refreshes.
 */
const PROVIDERS = new Set(["litellm-claude"])

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
        })
      }
    })
  },
}

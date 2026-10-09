/**
 * enmaas sends Anthropic requests through a gateway that validates them against an
 * older schema than the one OpenCode targets for the Opus 5.x family. Two fields
 * OpenCode emits are rejected outright:
 *
 *   thinking.block_binding   -> "thinking.adaptive.block_binding: Extra inputs are not permitted"
 *   messages[].output_config -> "messages.N.output_config: Extra inputs are not permitted"
 *
 * The second one arrives as a content-less `system` message that switches reasoning
 * effort mid-conversation, so the marker message has to be dropped entirely. Removing
 * only the field leaves an empty message and the gateway then rejects that instead
 * ("messages.N: system content must contain at least one block").
 *
 * Both fields are optional tuning hints, so dropping them keeps the request valid.
 */
export default {
  id: "enmaas-compat",
  async setup(ctx) {
    await ctx.session.hook(
      "http.request",
      async (event) => {
        const request = event.request
        if (request.method !== "POST") return
        if (!request.url.includes("/messages")) return

        const raw = await request.clone().text()
        if (!raw.includes("block_binding") && !raw.includes("output_config")) return

        let body
        try {
          body = JSON.parse(raw)
        } catch {
          return
        }

        let changed = false

        if (body.thinking?.block_binding !== undefined) {
          delete body.thinking.block_binding
          changed = true
        }

        if (Array.isArray(body.messages)) {
          const kept = body.messages.filter((message) => {
            if (message?.output_config === undefined) return true
            delete message.output_config
            changed = true
            const content = message.content
            const empty = Array.isArray(content) ? content.length === 0 : !content
            return !empty
          })
          if (kept.length !== body.messages.length) body.messages = kept
        }

        if (!changed) return

        event.request = new Request(request, { body: JSON.stringify(body) })
      },
      { providerID: "anthropic" },
    )
  },
}

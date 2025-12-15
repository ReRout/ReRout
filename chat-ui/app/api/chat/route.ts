import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { streamText, UIMessage, convertToModelMessages } from "ai";

export async function POST(req: Request) {
  const { messages }: { messages: UIMessage[] } = await req.json();
  
  // Create OpenAI-compatible provider for custom backend with custom fetch to add extra_body
  const provider = createOpenAICompatible({
    name: "rerout",
    baseURL: "http://localhost:8084/v1",
    headers: {
      "Content-Type": "application/json",
    },
    fetch: async (url, options) => {
      // Modify the request body to include extra_body for routing
      if (options?.body) {
        const body = JSON.parse(options.body as string);
        body.extra_body = {
          routing_policy: "task_router",
        };
        options.body = JSON.stringify(body);
      }
      return fetch(url, options);
    },
  });
  
  const result = streamText({
    // Use empty model string for auto-routing - backend will route based on routing_policy
    model: provider(""),
    messages: convertToModelMessages(messages),
  });

  return result.toUIMessageStreamResponse();
}

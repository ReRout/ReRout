import { createOpenAI } from "@ai-sdk/openai";
import { streamText, UIMessage, convertToModelMessages } from "ai";

export async function POST(req: Request) {
  const { messages }: { messages: UIMessage[] } = await req.json();
  
  // Create provider instance with custom configuration and custom fetch to add extra_body
  const provider = createOpenAI({
    baseURL: "http://localhost:8084/v1",
    apiKey: "dummy", // Not required for local backend
    fetch: async (url, options) => {
      // Modify the request body to include extra_body
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

This is the [assistant-ui](https://github.com/Yonom/assistant-ui) starter project integrated with RouteLLM.

## Getting Started

This chat UI is configured to use the local RouteLLM backend running on `http://localhost:8084`. Make sure your RouteLLM backend is running before starting the chat UI.

No API keys are required for local development - the backend handles routing automatically.

Then, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:4000](http://localhost:4000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

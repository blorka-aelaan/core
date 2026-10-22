import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { coreApi } from "./server/api.js";

// Tek `npm run dev`: hem pano (React) hem API (core sunucusu middleware)
export default defineConfig({
  plugins: [react(), coreApi()],
  server: { host: true, port: 5173, strictPort: true },
});

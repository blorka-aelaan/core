import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { coreApi } from "./server/api.js";
import fs from "node:fs";
import path from "node:path";

// API token'ı oku (sunucu tarafı da aynı dosyayı okur).
// Dosya yoksa bos string — sunucu o durumda yazma uclari fail-closed
// olarak kapatir (bkz. server/api.js → istekYetkili).
const TOKEN_DOSYA = process.env.CORE_API_TOKEN_FILE
  || path.join(process.env.HOME || "/root", ".core", "api_token");
function tokenOku() {
  if (process.env.CORE_API_TOKEN) return process.env.CORE_API_TOKEN.trim();
  try {
    return fs.readFileSync(TOKEN_DOSYA, "utf8").trim();
  } catch {
    return "";
  }
}

// Tek `npm run dev`: hem pano (React) hem API (core sunucusu middleware)
//
// GÜVENLİK: host "127.0.0.1" — pano YALNIZCA yerel makineden erişilebilir.
// `host: true` (0.0.0.0) LAN'a açar ve /api/manage gibi sudo çalıştıran
// uçları kimlik doğrulamasız hale getirir. Uzak erişim gerekirse SSH
// tüneli kullan:  ssh -L 5173:127.0.0.1:5173 <makine>
export default defineConfig({
  plugins: [react(), coreApi()],
  server: { host: "0.0.0.0", port: 5173, strictPort: true },
  // Yazma uçlarının token gönderebilmesi için frontend'e enjekte edilir.
  define: { __CORE_TOKEN__: JSON.stringify(tokenOku()) },
});

import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

// Sessiz boş-sayfa çökmesini önleyen hata sınırı.
class Sinir extends React.Component {
  constructor(p) { super(p); this.state = { hata: null }; }
  static getDerivedStateFromError(e) { return { hata: e }; }
  componentDidCatch(e, info) { console.error("Pano çökmesi:", e, info); }
  render() {
    if (this.state.hata) {
      return (
        <pre style={{ color: "#ff6b6b", background: "#1a120f",
          padding: 16, whiteSpace: "pre-wrap" }}>
          {"Pano bir bileşende çöktü:\n" +
            (this.state.hata?.stack || this.state.hata?.message || String(this.state.hata))}
        </pre>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")).render(
  <Sinir><App /></Sinir>
);

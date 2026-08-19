"use client";

import { X } from "lucide-react";
import { renderTextoComMascara } from "@/lib/mask";

export function FullDocModal({
  titulo,
  texto,
  carregando,
  onClose,
}: {
  titulo: string;
  texto: string | null;
  carregando: boolean;
  onClose: () => void;
}) {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 60, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "var(--surface-overlay)" }} />
      <div
        style={{
          position: "relative",
          width: 760,
          maxWidth: "100%",
          maxHeight: "100%",
          background: "var(--neutral-0)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "var(--shadow-lg)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: "18px 24px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 17, color: "var(--text-primary)" }}>{titulo}</div>
          <button onClick={onClose} aria-label="Fechar" style={{ width: 34, height: 34, borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)", background: "var(--neutral-0)", cursor: "pointer" }}>
            <X size={16} />
          </button>
        </div>
        <div style={{ padding: 24, overflowY: "auto", fontSize: 15, lineHeight: 1.7, color: "var(--text-primary)", whiteSpace: "pre-wrap" }}>
          {carregando ? "Carregando…" : texto ? renderTextoComMascara(texto) : "Não foi possível carregar o documento."}
        </div>
      </div>
    </div>
  );
}

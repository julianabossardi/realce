"use client";

import { X } from "lucide-react";
import { formatarDocumento } from "@/lib/formatarDocumento";
import { renderTextoComMascara } from "@/lib/mask";

export function FullDocModal({
  titulo,
  sintese,
  texto,
  carregando,
  erro,
  onClose,
}: {
  titulo: string;
  sintese?: string | null;
  texto: string | null;
  carregando: boolean;
  erro?: string;
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
        <div style={{ padding: "18px 24px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 17, color: "var(--text-primary)" }}>{titulo}</div>
            {sintese && (
              <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 6, lineHeight: 1.5 }}>{sintese}</div>
            )}
          </div>
          <button onClick={onClose} aria-label="Fechar" style={{ flexShrink: 0, width: 34, height: 34, borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)", background: "var(--neutral-0)", cursor: "pointer" }}>
            <X size={16} />
          </button>
        </div>
        <div style={{ padding: 24, overflowY: "auto", fontSize: 15, lineHeight: 1.7, color: "var(--text-primary)" }}>
          {carregando
            ? "Carregando…"
            : texto
            ? formatarDocumento(texto).map((bloco, i) =>
                bloco.tipo === "titulo" ? (
                  <div
                    key={i}
                    style={{
                      fontFamily: "var(--font-display)",
                      fontWeight: 700,
                      fontSize: 16,
                      color: "var(--text-primary)",
                      marginTop: i === 0 ? 0 : 20,
                      marginBottom: 10,
                    }}
                  >
                    {renderTextoComMascara(bloco.texto)}
                  </div>
                ) : (
                  <p key={i} style={{ margin: "0 0 14px", whiteSpace: "pre-wrap" }}>
                    {renderTextoComMascara(bloco.texto)}
                  </p>
                )
              )
            : erro || "Não foi possível carregar o documento."}
        </div>
      </div>
    </div>
  );
}

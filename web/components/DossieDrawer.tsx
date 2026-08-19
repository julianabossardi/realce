"use client";

import { X } from "lucide-react";
import type { DossieItem } from "@/lib/types";

export function DossieDrawer({
  itens,
  onClose,
  onRemove,
  onNotaChange,
}: {
  itens: DossieItem[];
  onClose: () => void;
  onRemove: (chunkId: string) => void;
  onNotaChange: (chunkId: string, nota: string) => void;
}) {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex", justifyContent: "flex-end" }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "var(--surface-overlay)" }} />
      <div
        style={{
          position: "relative",
          width: 440,
          maxWidth: "92vw",
          height: "100%",
          background: "var(--neutral-0)",
          boxShadow: "var(--shadow-lg)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            padding: "20px 24px",
            borderBottom: "1px solid var(--border-subtle)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
          }}
        >
          <div>
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 18, color: "var(--text-primary)" }}>
              Dossiê do caso
            </div>
            <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 2 }}>
              {itens.length} documento(s) reunido(s)
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Fechar"
            style={{ width: 34, height: 34, borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)", background: "var(--neutral-0)", cursor: "pointer" }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "16px 24px", display: "flex", flexDirection: "column", gap: 10 }}>
          {itens.length === 0 && (
            <div style={{ fontSize: 13, color: "var(--text-tertiary)", textAlign: "center", padding: "40px 0" }}>
              Nenhum documento salvo neste caso ainda.
            </div>
          )}
          {itens.map((it) => (
            <div key={it.id} style={{ border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", padding: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
                <div style={{ fontSize: 12, color: "var(--orange-700)" }}>
                  {it.titulo || it.arquivo_local} · {it.data_publicacao}
                </div>
                <button
                  onClick={() => onRemove(it.chunk_id)}
                  aria-label="Remover"
                  style={{ width: 28, height: 28, borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)", background: "var(--neutral-0)", cursor: "pointer", flexShrink: 0 }}
                >
                  <X size={14} />
                </button>
              </div>
              <div style={{ fontSize: 13, color: "var(--text-primary)", lineHeight: 1.5, margin: "6px 0" }}>
                {it.texto.slice(0, 160)}…
              </div>
              <input
                defaultValue={it.nota}
                onBlur={(e) => onNotaChange(it.chunk_id, e.target.value)}
                placeholder="Anotação (opcional)"
                style={{
                  width: "100%",
                  boxSizing: "border-box",
                  border: "1px solid var(--border-default)",
                  borderRadius: "var(--radius-sm)",
                  padding: "6px 8px",
                  fontSize: 12,
                  fontFamily: "var(--font-ui)",
                }}
              />
            </div>
          ))}
        </div>

        <div style={{ padding: "16px 24px", borderTop: "1px solid var(--border-subtle)" }}>
          <button
            disabled
            title="Exportação ainda não disponível nesta versão."
            style={{
              width: "100%",
              padding: "9px 0",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border-default)",
              background: "var(--neutral-100)",
              color: "var(--text-tertiary)",
              cursor: "not-allowed",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            Exportar dossiê
          </button>
        </div>
      </div>
    </div>
  );
}

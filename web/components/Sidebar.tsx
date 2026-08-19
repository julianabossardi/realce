"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import type { Caso } from "@/lib/types";

export function Sidebar({
  casos,
  activeCaseId,
  onSelectCase,
  onAddCase,
  onRenameCase,
  onGoHome,
}: {
  casos: Caso[];
  activeCaseId: string | null;
  onSelectCase: (id: string) => void;
  onAddCase: () => void;
  onRenameCase: (id: string, nome: string) => void;
  onGoHome: () => void;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  return (
    <div
      style={{
        width: 252,
        flexShrink: 0,
        height: "100%",
        background: "var(--gradient-glass-dark)",
        color: "#fff",
        display: "flex",
        flexDirection: "column",
        overflowY: "auto",
      }}
    >
      <div style={{ padding: "20px 20px 16px", borderBottom: "1px solid rgba(255,255,255,.08)" }}>
        <button
          onClick={onGoHome}
          style={{
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-start",
            color: "inherit",
          }}
        >
          <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 20 }}>Realce</span>
          <span style={{ fontSize: 11, color: "var(--orange-300)", marginTop: 2 }}>MPRJ</span>
        </button>
      </div>

      <div style={{ padding: "16px 14px 6px", fontSize: 11, fontWeight: 600, color: "var(--neutral-400)" }}>
        Casos abertos
      </div>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2, padding: "0 10px" }}>
        {casos.map((c) => {
          const isActive = c.id === activeCaseId;
          const isEditing = c.id === editingId;
          if (isEditing) {
            return (
              <input
                key={c.id}
                value={draft}
                autoFocus
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => {
                  onRenameCase(c.id, draft.trim() || "Novo caso");
                  setEditingId(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                }}
                style={{
                  background: "rgba(255,255,255,.12)",
                  border: "1px solid var(--orange-400)",
                  borderRadius: "var(--radius-sm)",
                  padding: "10px 12px",
                  color: "#fff",
                  fontSize: 14,
                  fontFamily: "var(--font-ui)",
                  outline: "none",
                  margin: "1px 0",
                }}
              />
            );
          }
          return (
            <button
              key={c.id}
              onClick={() => onSelectCase(c.id)}
              onDoubleClick={() => {
                setDraft(c.nome);
                setEditingId(c.id);
              }}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-start",
                gap: 2,
                padding: "9px 12px",
                border: "none",
                borderRadius: "var(--radius-sm)",
                background: isActive ? "rgba(198,99,31,.3)" : "transparent",
                color: isActive ? "#fff" : "var(--neutral-300)",
                cursor: "pointer",
                textAlign: "left",
                width: "100%",
              }}
              title="Clique duplo para renomear"
            >
              <span style={{ fontSize: 14, fontWeight: isActive ? 700 : 500 }}>{c.nome}</span>
              {c.numero_processo ? (
                <span style={{ fontSize: 11, color: isActive ? "var(--orange-200)" : "var(--neutral-500)" }}>
                  {c.numero_processo}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div style={{ padding: 10 }}>
        <button
          onClick={onAddCase}
          disabled={casos.length >= 10}
          title={casos.length >= 10 ? "Limite de 10 casos abertos simultaneamente." : "Adicionar novo caso."}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            width: "100%",
            boxSizing: "border-box",
            padding: "9px 12px",
            border: "1px dashed rgba(255,255,255,.25)",
            borderRadius: "var(--radius-sm)",
            background: "transparent",
            color: "var(--neutral-300)",
            fontSize: 13,
            cursor: casos.length >= 10 ? "not-allowed" : "pointer",
            opacity: casos.length >= 10 ? 0.5 : 1,
          }}
        >
          <Plus size={14} />
          Adicionar caso
        </button>
      </div>
    </div>
  );
}

"use client";

import type { Tag } from "@/lib/tags";

export function TagList({ tags, vazio }: { tags: Tag[]; vazio?: string }) {
  if (!tags.length) {
    return vazio ? <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>{vazio}</span> : null;
  }
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {tags.map((t, i) => (
        <span
          key={i}
          style={{
            background: t.tom === "criterio" ? "var(--neutral-100)" : "var(--surface-sunken)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-sm)",
            padding: "3px 9px",
            fontSize: 12,
            color: "var(--text-primary)",
          }}
        >
          {t.texto}
        </span>
      ))}
    </div>
  );
}

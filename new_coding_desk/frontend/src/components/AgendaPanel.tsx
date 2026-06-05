import { Circle, ListOrdered } from "lucide-react";
import { SectionCard, EmptyState } from "./shared";
import type { Agenda } from "../api/types";

interface AgendaPanelProps {
  agenda: Agenda[];
}

export function AgendaPanel({ agenda }: AgendaPanelProps) {
  const sorted = [...agenda].sort(
    (a, b) => (a.sort_order ?? a.id) - (b.sort_order ?? b.id),
  );

  return (
    <SectionCard
      title="Agenda"
      headerRight={
        <span className="text-xs text-slate-400 font-medium">
          {sorted.length} items
        </span>
      }
    >
      {sorted.length === 0 ? (
        <EmptyState
          icon={<ListOrdered size={20} />}
          title="No agenda items"
          description="Agenda items will appear here when set by the organizer."
        />
      ) : (
        <div className="space-y-1">
          {sorted.map((item) => (
            <AgendaRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function AgendaRow({ item }: { item: Agenda }) {
  return (
    <div className="flex items-start gap-3 rounded-xl px-3 py-2.5">
      <div className="mt-0.5 flex-shrink-0">
        <Circle size={16} className="text-slate-300" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-700 leading-snug">
          {item.title}
        </p>
      </div>
    </div>
  );
}

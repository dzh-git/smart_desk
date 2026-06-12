import { Circle, ListOrdered, Trash2 } from "lucide-react";
import { SectionCard, EmptyState } from "./shared";
import type { Agenda } from "../api/types";

interface AgendaPanelProps {
  agenda: Agenda[];
  onDelete?: (agendaId: number) => void;
  deleting?: boolean;
}

export function AgendaPanel({ agenda, onDelete, deleting = false }: AgendaPanelProps) {
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
            <AgendaRow
              key={item.id}
              item={item}
              onDelete={onDelete}
              deleting={deleting}
            />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function AgendaRow({
  item,
  onDelete,
  deleting,
}: {
  item: Agenda;
  onDelete?: (agendaId: number) => void;
  deleting: boolean;
}) {
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
      {onDelete && (
        <button
          onClick={() => onDelete(item.id)}
          disabled={deleting}
          className="inline-flex shrink-0 items-center justify-center rounded-md p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50"
          aria-label={`Delete agenda ${item.title}`}
        >
          <Trash2 size={13} />
        </button>
      )}
    </div>
  );
}

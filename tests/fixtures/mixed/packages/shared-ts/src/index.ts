export type Order = { id: string; total: number };

export function formatOrder(raw: any): Order {
  return { id: String(raw.id), total: Number(raw.total) };
}

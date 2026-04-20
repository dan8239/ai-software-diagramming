import React from "react";
import { Order } from "@acme/shared";

export function OrderList({ orders }: { orders: Order[] }) {
  return <ul>{orders.map((o) => <li key={o.id}>{o.id}</li>)}</ul>;
}

import axios from "axios";
import { formatOrder } from "@acme/shared";
import { OrderList } from "./components/OrderList";

export async function loadOrders() {
  const res = await axios.get("https://api.internal/orders");
  return res.data.map(formatOrder);
}

export { OrderList };

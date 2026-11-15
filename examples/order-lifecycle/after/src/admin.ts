import { OrderStatus } from "@prisma/client";
import { transition } from "./transition";

// The admin panel cannot set a state. It can only ask for a legal move, and it
// has to say who asked and why.
export async function cancelOrder(orderId: string, actorId: string, reason: string) {
  await transition(orderId, OrderStatus.PENDING, OrderStatus.CANCELLED, actorId, reason);
}

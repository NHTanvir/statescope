import { OrderStatus } from "@prisma/client";
import { transition } from "./transition";

export async function markPaid(orderId: string, actorId: string) {
  await transition(orderId, OrderStatus.PENDING, OrderStatus.PAID, actorId);
}

export async function ship(orderId: string, actorId: string) {
  await transition(orderId, OrderStatus.PAID, OrderStatus.SHIPPED, actorId);
}

export async function deliver(orderId: string, actorId: string) {
  await transition(orderId, OrderStatus.SHIPPED, OrderStatus.DELIVERED, actorId);
}

// There is no "retry" and no "unship". A delivered order that needs to move
// again is a new order, and a refund is its own edge out of PAID.
export async function refund(orderId: string, actorId: string, reason: string) {
  await transition(orderId, OrderStatus.PAID, OrderStatus.REFUNDED, actorId, reason);
}

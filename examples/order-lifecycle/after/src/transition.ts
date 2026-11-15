import { OrderStatus } from "@prisma/client";
import { prisma } from "./db";

export class IllegalTransition extends Error {}
export class ConcurrentTransition extends Error {}

// The machine, in one place. This table is the only thing that defines it.
const ALLOWED: Record<OrderStatus, OrderStatus[]> = {
  PENDING: [OrderStatus.PAID, OrderStatus.CANCELLED],
  PAID: [OrderStatus.SHIPPED, OrderStatus.REFUNDED],
  SHIPPED: [OrderStatus.DELIVERED],
  DELIVERED: [],
  CANCELLED: [],
  REFUNDED: [],
};

/**
 * Move one order from `from` to `to`, or refuse.
 *
 * The WHERE clause carries the expected state, so two concurrent callers cannot
 * both win: the second one updates zero rows and is told so.
 */
export async function transition(
  orderId: string,
  from: OrderStatus,
  to: OrderStatus,
  actorId: string | null,
  reason?: string,
): Promise<void> {
  if (!ALLOWED[from].includes(to)) {
    throw new IllegalTransition(`${from} -> ${to} is not a legal move`);
  }

  await prisma.$transaction(async (tx) => {
    const { count } = await tx.order.updateMany({
      where: { id: orderId, status: from },
      data: { status: to, statusChangedAt: new Date() },
    });
    if (count === 0) {
      throw new ConcurrentTransition(
        `${orderId} was not in ${from} when the move was attempted`,
      );
    }
    await tx.orderStatusHistory.create({
      data: { orderId, from, to, actorId, reason },
    });
  });
}

import { prisma } from "./db";

// The happy path. This one is guarded, and it is the only one that is.
export async function markPaid(orderId: string) {
  const order = await prisma.order.findUnique({ where: { id: orderId } });
  if (order.status === "pending") {
    await prisma.order.update({
      where: { id: orderId },
      data: { status: "paid" },
    });
  }
}

export async function ship(orderId: string) {
  const order = await prisma.order.findUnique({ where: { id: orderId } });
  if (order.status === "paid") {
    await prisma.order.update({
      where: { id: orderId },
      data: { status: "shipped" },
    });
  }
}

export async function deliver(orderId: string) {
  const order = await prisma.order.findUnique({ where: { id: orderId } });
  if (order.status === "shipped") {
    await prisma.order.update({
      where: { id: orderId },
      data: { status: "delivered" },
    });
  }
}

// Support asked for a "retry" button. Nobody asked what it should refuse.
export async function retryOrder(orderId: string) {
  const order = await prisma.order.findUnique({ where: { id: orderId } });
  if (order.status === "refunded" || order.status === "cancelled") {
    await prisma.order.update({
      where: { id: orderId },
      data: { status: "pending" },
    });
  }
}

// The warehouse printed the wrong label, so we "unship" it.
export async function unship(orderId: string) {
  const order = await prisma.order.findUnique({ where: { id: orderId } });
  if (order.status === "shipped") {
    await prisma.order.update({
      where: { id: orderId },
      data: { status: "paid" },
    });
  }
}

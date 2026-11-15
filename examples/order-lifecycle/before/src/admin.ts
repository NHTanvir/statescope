import { prisma } from "./db";

// The admin tool. One form field, one write, no questions asked.
export async function setOrderStatus(orderId: string, status: string) {
  await prisma.order.update({ where: { id: orderId }, data: { status } });
}

export async function cancelOrder(orderId: string) {
  await prisma.order.update({
    where: { id: orderId },
    data: { status: "cancelled" },
  });
}

// Used by the "clear test data" script. Also exposed on the admin panel.
export async function resetOrder(orderId: string) {
  await prisma.order.update({
    where: { id: orderId },
    data: { status: "pending" },
  });
}

import { prisma } from "./db";

// Stripe calls this. It trusts the event and writes whatever it implies.
export async function onPaymentWebhook(event: { orderId: string; type: string }) {
  if (event.type === "charge.refunded") {
    await prisma.order.update({
      where: { id: event.orderId },
      data: { status: "refunded" },
    });
  }
  if (event.type === "charge.succeeded") {
    await prisma.order.update({
      where: { id: event.orderId },
      data: { status: "paid" },
    });
  }
}

export async function onShippingWebhook(orderId: string) {
  await prisma.order.update({
    where: { id: orderId },
    data: { status: "delivered" },
  });
}

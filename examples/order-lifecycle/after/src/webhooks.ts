import { OrderStatus } from "@prisma/client";
import { transition, ConcurrentTransition } from "./transition";

// Stripe retries. Asking for a move that already happened is not an error here,
// it is the retry arriving late, so it is swallowed deliberately and logged.
export async function onPaymentWebhook(event: { orderId: string; type: string }) {
  try {
    if (event.type === "charge.succeeded") {
      await transition(event.orderId, OrderStatus.PENDING, OrderStatus.PAID, null);
    }
    if (event.type === "charge.refunded") {
      await transition(event.orderId, OrderStatus.PAID, OrderStatus.REFUNDED, null);
    }
  } catch (err) {
    if (!(err instanceof ConcurrentTransition)) throw err;
    console.info("webhook arrived after the state already moved", event.orderId);
  }
}

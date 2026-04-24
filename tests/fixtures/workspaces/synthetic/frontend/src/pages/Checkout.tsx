import { createCheckout, getCheckout } from "../api/client";
export default function Checkout() {
  return <button onClick={() => createCheckout({items: ["x"]})}>Buy</button>;
}

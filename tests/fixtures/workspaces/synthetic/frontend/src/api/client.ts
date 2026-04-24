export async function createCheckout(payload: {items: string[]}) {
  return fetch("/checkout", {method: "POST", body: JSON.stringify(payload)});
}
export async function getCheckout(id: string) {
  return fetch(`/checkout/${id}`);
}
export async function listPricing() {
  return fetch("/pricing");
}
export async function getPricing(sku: string) {
  return fetch(`/pricing/${sku}`);
}
export async function listUsers() {
  return fetch("/users");
}
export async function createUser(payload: {name: string}) {
  return fetch("/users", {method: "POST", body: JSON.stringify(payload)});
}
export async function getUser(id: string) {
  return fetch(`/users/${id}`);
}
export async function setUserRoles(id: string, roles: string[]) {
  return fetch(`/users/${id}/roles`, {method: "PUT", body: JSON.stringify(roles)});
}

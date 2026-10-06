const BASE="https://ai-customer-support-chatbot-r89k.vercel.app/api";
export const token=()=>localStorage.getItem("token");
export async function api(path,opts={}){
 const headers=new Headers(opts.headers||{});
 if (!(opts.body instanceof FormData) && !headers.has("Content-Type")) {
  headers.set("Content-Type","application/json");
 }
 const authToken=token();
 if (authToken) headers.set("Authorization",`Bearer ${authToken}`);
 let r;
 try {
  r=await fetch(BASE+path,{...opts,headers});
 } catch {
  throw new Error("Backend is not reachable. Please try again.");
 }
 let data={};
 try { data=await r.json(); } catch { data={}; }
 const errorMessage=(data.error || data.msg || data.message || "").toLowerCase();
 const invalidSession = [401, 422].includes(r.status) && (
  errorMessage.includes("signature") ||
  errorMessage.includes("token") ||
  errorMessage.includes("expired") ||
  errorMessage.includes("authorization") ||
  errorMessage.includes("session") ||
  errorMessage.includes("invalid header") ||
  errorMessage.includes("header padding")
 );
 if (r.status===401 || invalidSession) {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
  window.location.reload();
  throw new Error("Your session expired. Please log in again.");
 }
 if(!r.ok) throw new Error(data.error || data.msg || data.message || "Request failed");
 return data;
}

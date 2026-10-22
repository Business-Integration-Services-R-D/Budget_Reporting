import { HIDE_NUMBERS, HIDDEN_VALUE } from "./privacy";
import axios from "axios";

// Akıllı Backend URL tespiti:
// 1. process.env.REACT_APP_BACKEND_URL'i öncelikli kullan (development/preview için)
// 2. AMA frontend custom domain'den açılıyorsa (env'deki hostname ile uyuşmuyorsa),
//    mevcut domain'in /api endpoint'ini kullan → custom domain'lerde otomatik çalışır
const ENV_BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";

const resolveBackendURL = () => {
  if (typeof window === "undefined") return ENV_BACKEND_URL;
  const currentHost = window.location.hostname;
  // Env URL ya hiç yok ya da farklı bir hostname içeriyorsa → mevcut origin kullan
  if (!ENV_BACKEND_URL) return window.location.origin;
  try {
    const envHost = new URL(ENV_BACKEND_URL).hostname;
    if (envHost !== currentHost) {
      // Custom domain veya farklı domain → mevcut origin'i kullan
      return window.location.origin;
    }
  } catch {
    return window.location.origin;
  }
  return ENV_BACKEND_URL;
};

const BACKEND_URL = resolveBackendURL();
export const API_BASE = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

// Token interceptor (localStorage fallback)
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("ey_token");
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && !window.location.pathname.startsWith("/login")) {
      localStorage.removeItem("ey_token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export const formatApiError = (e) => {
  const d = e?.response?.data?.detail;
  if (!d) return e?.message || "Bir hata oluştu";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(" ");
  return JSON.stringify(d);
};

export const fmtUSD = (n, signed = false) =>
  HIDE_NUMBERS ? HIDDEN_VALUE : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0, signDisplay: signed ? "exceptZero" : "auto" }).format(n || 0);

export const fmtNum = (n, digits = 2) =>
  HIDE_NUMBERS ? HIDDEN_VALUE : new Intl.NumberFormat("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n || 0);

export const fmtDate = (s) => {
  if (!s) return "—";
  try {
    const d = new Date(s);
    return d.toLocaleDateString("tr-TR", { year: "numeric", month: "short", day: "2-digit" });
  } catch {
    return s;
  }
};

export const fmtDateShort = (s) => {
  if (!s) return "—";
  try {
    const d = new Date(s);
    return d.toLocaleDateString("tr-TR", { month: "2-digit", day: "2-digit" });
  } catch {
    return s;
  }
};

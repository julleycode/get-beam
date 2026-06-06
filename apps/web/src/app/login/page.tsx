"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

function BeamLogo() {
  return (
    <svg viewBox="0 0 100 64" className="w-12 h-12" aria-hidden="true">
      <defs>
        <linearGradient id="beamGrad" x1="0" y1="0" x2="1" y2="0.35">
          <stop offset="0" stopColor="#FF6B9D" />
          <stop offset="0.55" stopColor="#FF3366" />
          <stop offset="1" stopColor="#FF7FA8" />
        </linearGradient>
      </defs>
      <path
        d="M26,15 Q26,32 90,32 Q26,32 26,49 Q26,32 9,32 Q26,32 26,15 Z"
        fill="url(#beamGrad)"
      />
      <circle cx="26" cy="32" r="3.4" fill="#fff" opacity="0.92" />
      <path
        d="M82,21 Q84,25 88,25 Q84,25 82,29 Q80,25 76,25 Q80,25 82,21 Z"
        fill="url(#beamGrad)"
        opacity="0.85"
      />
      <circle cx="89" cy="40" r="2.1" fill="url(#beamGrad)" opacity="0.7" />
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const result = await api.login(email, password);
      api.setToken(result.access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4 bg-[#FAF6F0]">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-[0_2px_8px_rgba(43,37,48,0.08),0_20px_50px_-20px_rgba(43,37,48,0.12)]">
        <div className="flex flex-col items-center mb-8">
          <BeamLogo />
          <h1 className="text-2xl font-bold mt-3 text-[#2B2530]">beam</h1>
          <p className="text-sm text-[#8C8295] mt-1">
            Sign in to your account
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}
          <div className="space-y-1.5">
            <label htmlFor="email" className="text-sm font-medium text-[#2B2530]">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-lg border border-[#E9DFCD] bg-white px-3 py-2 text-sm text-[#2B2530] placeholder:text-[#8C8295] focus:outline-none focus:ring-2 focus:ring-[#FF3366]/30 focus:border-[#FF3366]"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="password" className="text-sm font-medium text-[#2B2530]">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-lg border border-[#E9DFCD] bg-white px-3 py-2 text-sm text-[#2B2530] placeholder:text-[#8C8295] focus:outline-none focus:ring-2 focus:ring-[#FF3366]/30 focus:border-[#FF3366]"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-[#FF3366] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#e6295a] disabled:opacity-50 transition-colors"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
          <p className="text-center text-sm text-[#8C8295]">
            No account?{" "}
            <Link href="/signup" className="text-[#FF3366] hover:text-[#e6295a] underline">
              Sign up
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}

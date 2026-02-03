import { useEffect, useState, useRef } from "react";
import { API_BASE_URL } from "../config";

export default function AuthCallback() {
  const [message, setMessage] = useState("Processing login...");
  const [error, setError] = useState(null);
  const hasProcessed = useRef(false);

  useEffect(() => {
    // Prevent duplicate calls in React StrictMode
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const handleCallback = async () => {
      try {
        const params = new URLSearchParams(window.location.search);
        const code = params.get("code");
        const codeVerifier = sessionStorage.getItem("pkce_code_verifier");

        if (!code || !codeVerifier) {
          setError("Missing code or code_verifier");
          return;
        }

        const response = await fetch(`${API_BASE_URL}/v1/auth/callback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, code_verifier: codeVerifier })
        });

        if (!response.ok) {
          const err = await response.json();
          throw new Error(err.detail || "Authentication failed");
        }

        const data = await response.json();
        localStorage.setItem("access_token", data.access_token);
        localStorage.setItem("user", JSON.stringify(data.user));
        
        // Store id_token separately for logout
        if (data.user.id_token) {
          localStorage.setItem("id_token", data.user.id_token);
        }

        setTimeout(() => {
          window.location.href = "/";
        }, 1000);
      } catch (err) {
        setError(err.message);
      }
    };

    handleCallback();
  }, []);

  return (
    <div style={{ 
      display: "flex", 
      alignItems: "center", 
      justifyContent: "center", 
      height: "100vh",
      backgroundColor: "#f0f0f0"
    }}>
      <div style={{
        backgroundColor: "white",
        padding: "40px",
        borderRadius: "8px",
        boxShadow: "0 2px 10px rgba(0,0,0,0.1)",
        textAlign: "center",
        width: "100%",
        maxWidth: "300px"
      }}>
        {error ? (
          <>
            <h2 style={{ color: "red", marginTop: 0 }}>Error</h2>
            <p>{error}</p>
            <a href="/login" style={{ color: "#007bff" }}>Back to Login</a>
          </>
        ) : (
          <>
            <h2 style={{ margin: "0 0 20px 0" }}>✅</h2>
            <p style={{ margin: 0 }}>{message}</p>
          </>
        )}
      </div>
    </div>
  );
}

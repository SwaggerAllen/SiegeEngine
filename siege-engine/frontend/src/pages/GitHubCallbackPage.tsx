import { useEffect } from 'react';

export function GitHubCallbackPage() {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');

    if (code && state && window.opener) {
      window.opener.postMessage({ type: 'github-oauth', code, state }, window.location.origin);
    }
    window.close();
  }, []);

  return (
    <div className="h-screen flex items-center justify-center bg-gray-900 text-white text-sm">
      Completing GitHub connection...
    </div>
  );
}

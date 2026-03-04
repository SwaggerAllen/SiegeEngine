import { useEffect, useState } from 'react';
import api from '../../api/client';

interface Invite {
  id: string;
  token: string;
  url: string;
  expires_at: string;
  used: boolean;
  created_at: string;
}

export function InvitePanel({ onClose }: { onClose: () => void }) {
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const fetchInvites = async () => {
    const { data } = await api.get('/auth/invites');
    setInvites(data);
  };

  useEffect(() => {
    fetchInvites();
  }, []);

  const createInvite = async () => {
    setLoading(true);
    try {
      await api.post('/auth/invites');
      await fetchInvites();
    } finally {
      setLoading(false);
    }
  };

  const revokeInvite = async (id: string) => {
    await api.delete(`/auth/invites/${id}`);
    await fetchInvites();
  };

  const copyLink = (invite: Invite) => {
    const url = `${window.location.origin}${invite.url}`;
    navigator.clipboard.writeText(url);
    setCopiedId(invite.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white">Invite Links</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white text-xl"
          >
            &times;
          </button>
        </div>

        <button
          onClick={createInvite}
          disabled={loading}
          className="w-full mb-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm disabled:opacity-50"
        >
          {loading ? 'Generating...' : 'Generate Invite Link'}
        </button>

        {invites.length === 0 ? (
          <p className="text-gray-500 text-sm text-center">No active invites</p>
        ) : (
          <div className="space-y-2 max-h-64 overflow-auto">
            {invites.map((inv) => (
              <div
                key={inv.id}
                className="bg-gray-700 p-3 rounded flex items-center justify-between"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white font-mono truncate">
                    {window.location.origin}{inv.url}
                  </p>
                  <p className="text-xs text-gray-400">
                    Expires: {new Date(inv.expires_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex items-center gap-2 ml-2 shrink-0">
                  <button
                    onClick={() => copyLink(inv)}
                    className="px-2 py-1 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded"
                  >
                    {copiedId === inv.id ? 'Copied!' : 'Copy'}
                  </button>
                  <button
                    onClick={() => revokeInvite(inv.id)}
                    className="px-2 py-1 bg-red-600 hover:bg-red-700 text-white text-xs rounded"
                  >
                    Revoke
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

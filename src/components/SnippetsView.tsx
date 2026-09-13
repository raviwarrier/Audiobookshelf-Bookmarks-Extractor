import React, { useState } from 'react';
import { 
  Search, 
  Download, 
  Copy, 
  Trash2, 
  Check, 
  FileText, 
  FileAudio,
  BookmarkPlus,
  FolderTree,
  User as UserIcon,
  RefreshCw
} from 'lucide-react';
import { Snippet, AbsUser } from '../types';

interface SnippetsViewProps {
  snippets: Snippet[];
  user: AbsUser | null;
  onDeleteSnippet: (id: string) => void;
  onNavigateToCapture: () => void;
  onRefreshSnippets?: () => Promise<void>;
  isLoadingSnippets?: boolean;
}

export const SnippetsView: React.FC<SnippetsViewProps> = ({
  snippets,
  user,
  onDeleteSnippet,
  onNavigateToCapture,
  onRefreshSnippets,
  isLoadingSnippets = false,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const filteredSnippets = snippets.filter(
    (s) =>
      s.bookTitle.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.author.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.chapterName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.transcript.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleCopyTranscript = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleDownloadMarkdown = (snippet: Snippet) => {
    const blob = new Blob([snippet.markdownContent], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${snippet.bookTitle.replace(/\s+/g, '_')}_${snippet.timestamp}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleDownloadAudio = async (snippet: Snippet) => {
    if (!snippet.audioUrl) return;
    try {
      // Fetch blob to reliably download the MP3 file without opening new tabs or failing on external hosts
      const res = await fetch(snippet.audioUrl);
      if (res.ok) {
        const blob = await res.blob();
        const blobUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = `${snippet.bookTitle.replace(/\s+/g, '_')}_${snippet.timestamp}.mp3`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(blobUrl);
        return;
      }
    } catch (err) {
      console.warn('Direct blob audio download failed, falling back to direct link:', err);
    }
    const link = document.createElement('a');
    link.href = snippet.audioUrl;
    link.download = `${snippet.bookTitle.replace(/\s+/g, '_')}_${snippet.timestamp}.mp3`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      
      {/* Header & Search Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-neutral-800 pb-4">
        <div>
          <h2 className="text-base font-semibold text-white tracking-tight uppercase">
            Saved Bookmarks & Transcripts
          </h2>
          <p className="text-xs text-neutral-400 mt-0.5">
            {snippets.length} audio clips & markdown files in library
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative w-full sm:w-64">
            <Search className="w-3.5 h-3.5 text-neutral-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search transcripts or books..."
              className="w-full bg-[#181818] border border-neutral-700 hover:border-neutral-500 focus:border-neutral-300 focus:bg-[#202020] pl-8 pr-3 py-1.5 text-xs text-white placeholder-neutral-500 focus:outline-none transition-colors font-mono"
            />
          </div>

          {onRefreshSnippets && (
            <button
              onClick={onRefreshSnippets}
              disabled={isLoadingSnippets}
              title="Sync bookmarks from server volume"
              className="px-2.5 py-1.5 border border-neutral-700 bg-[#161616] hover:bg-[#222222] hover:border-neutral-500 text-xs text-neutral-200 transition-colors flex items-center gap-1.5 disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoadingSnippets ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Sync</span>
            </button>
          )}

          <button
            onClick={onNavigateToCapture}
            className="px-3 py-1.5 bg-neutral-100 text-black hover:bg-white text-xs font-semibold flex items-center gap-1.5 shrink-0 transition-colors"
          >
            <BookmarkPlus className="w-3.5 h-3.5" />
            <span>New Snippet</span>
          </button>
        </div>
      </div>

      {/* User-specific Volume Directory Scope Banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 bg-[#0e0e0e] border border-neutral-700 text-xs text-neutral-300 font-mono">
        <div className="flex items-center gap-2">
          <FolderTree className="w-3.5 h-3.5 text-neutral-400" />
          <span className="text-neutral-400">Volume Storage:</span>
          <span className="text-white font-semibold">
            {user ? `${user.username}/bookmarks/` : 'username/bookmarks/'}
          </span>
          <span className="text-[10px] bg-neutral-800 text-neutral-400 px-1.5 py-0.5 border border-neutral-700">
            User Isolated
          </span>
        </div>
        {user && (
          <div className="flex items-center gap-1.5 text-neutral-400">
            <UserIcon className="w-3 h-3 text-neutral-400" />
            <span>Logged in as:</span>
            <span className="text-white font-medium">@{user.username}</span>
          </div>
        )}
      </div>

      {/* Snippet List */}
      {filteredSnippets.length === 0 ? (
        <div className="border border-neutral-700 bg-[#0d0d0d] p-12 text-center space-y-4">
          <div className="text-neutral-400 text-sm font-mono">
            {searchTerm ? 'No matching snippets found.' : 'No snippets captured yet.'}
          </div>
          <button
            onClick={onNavigateToCapture}
            className="px-4 py-2 border border-neutral-700 bg-[#161616] text-xs text-neutral-200 hover:text-white hover:border-neutral-500 transition-colors"
          >
            Go to Capture Screen →
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredSnippets.map((snippet) => (
            <article
              key={snippet.id}
              className="border border-neutral-700 bg-[#0d0d0d] p-5 space-y-4"
            >
              {/* Snippet Header */}
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2 border-b border-neutral-800 pb-3">
                <div>
                  <h3 className="text-sm font-semibold text-white">
                    {snippet.bookTitle}
                  </h3>
                  <div className="text-xs text-neutral-400 mt-0.5 flex flex-wrap items-center gap-2">
                    <span>{snippet.author}</span>
                    <span>•</span>
                    <span>{snippet.chapterName}</span>
                    <span className="text-[10px] text-neutral-400 bg-neutral-800 px-1.5 py-0.5 border border-neutral-700">
                      @{snippet.username || user?.username || 'user'}
                    </span>
                    <span className="text-[10px] text-neutral-500 hidden sm:inline">
                      {snippet.username || user?.username || 'user'}/bookmarks/
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-3 text-xs text-neutral-400 font-mono self-end sm:self-auto">
                  <span>Start: {snippet.startTime}s</span>
                  <span>Duration: {snippet.duration}s</span>
                  <span>{new Date(snippet.createdAt).toLocaleDateString()}</span>
                </div>
              </div>

              {/* Audio Player */}
              <div className="bg-[#141414] p-2.5 border border-neutral-700">
                <audio
                  controls
                  src={snippet.audioUrl}
                  className="w-full h-8 bg-[#181818]"
                />
              </div>

              {/* Transcript Text Box */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs text-neutral-400">
                  <span className="font-mono text-[11px] uppercase">Whisper Transcript</span>
                  <button
                    onClick={() => handleCopyTranscript(snippet.id, snippet.transcript)}
                    className="flex items-center gap-1 text-neutral-300 hover:text-white transition-colors"
                  >
                    {copiedId === snippet.id ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-white" />
                        <span>Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5" />
                        <span>Copy Text</span>
                      </>
                    )}
                  </button>
                </div>

                <div className="p-3 bg-[#151515] border border-neutral-700 text-xs text-neutral-200 leading-relaxed font-mono whitespace-pre-wrap">
                  {snippet.transcript}
                </div>
              </div>

              {/* Action Toolbar */}
              <div className="flex items-center justify-between pt-2 border-t border-neutral-800 text-xs">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleDownloadAudio(snippet)}
                    className="flex items-center gap-1.5 px-3 py-1.5 border border-neutral-700 bg-[#161616] hover:border-neutral-500 text-neutral-200 hover:text-white transition-colors"
                  >
                    <FileAudio className="w-3.5 h-3.5" />
                    <span>Download .MP3</span>
                  </button>

                  <button
                    onClick={() => handleDownloadMarkdown(snippet)}
                    className="flex items-center gap-1.5 px-3 py-1.5 border border-neutral-700 bg-[#161616] hover:border-neutral-500 text-neutral-200 hover:text-white transition-colors"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    <span>Download .MD</span>
                  </button>
                </div>

                <button
                  onClick={() => onDeleteSnippet(snippet.id)}
                  className="text-neutral-400 hover:text-red-400 flex items-center gap-1 transition-colors"
                  title="Delete snippet"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>Delete</span>
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

    </div>
  );
};

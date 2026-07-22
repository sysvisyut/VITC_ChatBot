import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Copy, Check, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "@/hooks/use-toast";
import { Source } from "@/types/chat";

interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  sources?: Source[];
  confidence?: "high" | "medium" | "low";
}

export const MessageBubble = ({ role, content, timestamp, sources, confidence }: MessageBubbleProps) => {
  const [copied, setCopied] = useState(false);
  const [showSources, setShowSources] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      toast({ title: "Copied to clipboard!" });
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      toast({ title: "Failed to copy", variant: "destructive" });
    }
  };

  const formatTime = (date: Date) => {
    return new Intl.DateTimeFormat("en-US", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  };

  // Deduplicate by document_name — the unique key in the actual API response.
  const uniqueSources = sources
    ? Array.from(new Set(sources.map((s) => s.document_name))).map((name) => (
        sources.find((s) => s.document_name === name)!
      ))
    : [];

  if (role === "user") {
    return (
      <div className="flex justify-end mb-6 animate-fade-in">
        <div className="max-w-[75%] md:max-w-[65%]">
          <div className="gradient-user text-primary-foreground rounded-2xl rounded-tr-md px-5 py-3 shadow-soft">
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{content}</p>
          </div>
          <p className="text-xs text-muted-foreground mt-1 text-right">{formatTime(timestamp)}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start mb-6 animate-fade-in">
      <div className="max-w-[85%] md:max-w-[75%]">
        <div className="bg-card border border-border rounded-2xl rounded-tl-md px-5 py-4 shadow-soft">
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <ReactMarkdown
              components={{
                code({ node, className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || "");
                  const isInline = !match;
                  
                  if (isInline) {
                    return (
                      <code className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono" {...props}>
                        {children}
                      </code>
                    );
                  }
                  
                  return (
                    <code className={`${className} block bg-muted p-3 rounded-lg text-sm font-mono overflow-x-auto`} {...props}>
                      {children}
                    </code>
                  );
                },
                p: ({ children }) => <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>,
                ul: ({ children }) => <ul className="list-disc pl-5 mb-3 space-y-1">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal pl-5 mb-3 space-y-1">{children}</ol>,
                li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
                h1: ({ children }) => <h1 className="text-xl font-bold mb-2 mt-4 first:mt-0">{children}</h1>,
                h2: ({ children }) => <h2 className="text-lg font-semibold mb-2 mt-3 first:mt-0">{children}</h2>,
                h3: ({ children }) => <h3 className="text-base font-semibold mb-2 mt-3 first:mt-0">{children}</h3>,
              }}
            >
              {content}
            </ReactMarkdown>
          </div>

          <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
            <div className="flex items-center gap-2">
              <p className="text-xs text-muted-foreground">{formatTime(timestamp)}</p>
              {confidence && (
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    confidence === "high"
                      ? "bg-green-500/15 text-green-600 dark:text-green-400"
                      : confidence === "medium"
                      ? "bg-yellow-500/15 text-yellow-600 dark:text-yellow-400"
                      : "bg-orange-500/15 text-orange-600 dark:text-orange-400"
                  }`}
                >
                  {confidence === "high" ? "✓ High confidence"
                    : confidence === "medium" ? "~ Medium confidence"
                    : "! Low confidence"}
                </span>
              )}
            </div>
            <Button
              onClick={handleCopy}
              variant="ghost"
              size="sm"
              className="h-7 px-2 gap-1.5 text-xs"
            >
              {copied ? (
                <>
                  <Check className="h-3 w-3" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3" />
                  Copy
                </>
              )}
            </Button>
          </div>

          {uniqueSources.length > 0 && (
            <div className="mt-3 pt-3 border-t border-border">
              <button
                onClick={() => setShowSources(!showSources)}
                className="flex items-center gap-2 text-sm font-medium text-primary hover:text-primary-glow transition-colors w-full"
              >
                <span className="flex items-center gap-2">
                  <span className="bg-primary/10 text-primary text-xs px-2 py-0.5 rounded-full">
                    {uniqueSources.length}
                  </span>
                  {uniqueSources.length === 1 ? "Source" : "Sources"}
                </span>
                {showSources ? (
                  <ChevronUp className="h-4 w-4 ml-auto" />
                ) : (
                  <ChevronDown className="h-4 w-4 ml-auto" />
                )}
              </button>

              {showSources && (
                <div className="mt-3 space-y-2 animate-fade-in">
                  {uniqueSources.map((source, index) => (
                    <div
                      key={index}
                      className="bg-muted/50 rounded-lg px-3 py-2 text-xs"
                    >
                      <p className="font-medium text-foreground mb-1">
                        📄 {source.document_name}
                      </p>
                      <p className="text-muted-foreground">
                        Page {source.page_number}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

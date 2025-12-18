"use client";

import { useMemo } from "react";

// Type for the metadata embedded in message content
export interface ReroutMetadata {
  model: string;
  cost: {
    total_cost_usd: number;
    prompt_tokens: number;
    completion_tokens: number;
  };
  comparison: {
    model: string;
    total_cost: number;
    savings_amount: number;
    savings_percentage: number;
  };
  routing?: {
    source: string;
    chosen: string;
    intent?: string;
    intent_confidence?: number;
    complexity?: string;
    complexity_confidence?: number;
  };
}

// Regex to extract metadata from message content
const METADATA_REGEX =
  /<!-- REROUT_META:(.*?):REROUT_META -->/s;

/**
 * Extract metadata from message content and return clean content + metadata
 */
export function extractMetadata(content: string): {
  cleanContent: string;
  metadata: ReroutMetadata | null;
} {
  const match = content.match(METADATA_REGEX);
  if (!match) {
    return { cleanContent: content, metadata: null };
  }

  try {
    const metadata = JSON.parse(match[1]) as ReroutMetadata;
    const cleanContent = content.replace(METADATA_REGEX, "").trim();
    return { cleanContent, metadata };
  } catch {
    return { cleanContent: content, metadata: null };
  }
}

/**
 * Format a cost value for display
 */
function formatCost(cost: number): string {
  if (cost === 0) return "$0.00";
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

/**
 * Extract model name from provider/model format
 */
function getModelDisplayName(fullModel: string): string {
  if (!fullModel) return "Unknown";
  const parts = fullModel.split("/");
  // Get the last part and clean it up
  const modelName = parts[parts.length - 1] || parts[0];
  // Remove common suffixes like :free
  return modelName.replace(/:free$/, "").replace(/-instruct$/, "");
}

/**
 * Get complexity badge styling based on level
 */
function getComplexityStyle(complexity: string): { bg: string; text: string; label: string } {
  switch (complexity?.toLowerCase()) {
    case "low":
      return {
        bg: "bg-blue-500/10 dark:bg-blue-500/20",
        text: "text-blue-600 dark:text-blue-400",
        label: "Simple",
      };
    case "medium":
      return {
        bg: "bg-amber-500/10 dark:bg-amber-500/20",
        text: "text-amber-600 dark:text-amber-400",
        label: "Medium",
      };
    case "high":
      return {
        bg: "bg-rose-500/10 dark:bg-rose-500/20",
        text: "text-rose-600 dark:text-rose-400",
        label: "Complex",
      };
    default:
      return {
        bg: "bg-gray-500/10 dark:bg-gray-500/20",
        text: "text-gray-600 dark:text-gray-400",
        label: complexity || "Unknown",
      };
  }
}

/**
 * Format intent for display
 */
function formatIntent(intent: string): string {
  if (!intent) return "";
  return intent
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

interface CostBadgeProps {
  metadata: ReroutMetadata;
}

export function CostBadge({ metadata }: CostBadgeProps) {
  const { model, cost, comparison, routing } = metadata;

  const displayModel = useMemo(() => getModelDisplayName(model), [model]);
  const actualCost = formatCost(cost.total_cost_usd);
  const comparisonCost = formatCost(comparison.total_cost);
  const savingsPercent = comparison.savings_percentage;

  const complexity = routing?.complexity;
  const intent = routing?.intent;
  const complexityStyle = useMemo(
    () => (complexity ? getComplexityStyle(complexity) : null),
    [complexity]
  );

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      {/* Model name */}
      <span className="font-medium text-foreground/70">{displayModel}</span>

      <span className="text-muted-foreground/50">·</span>

      {/* Actual cost */}
      <span>{actualCost}</span>

      {/* Complexity badge */}
      {complexityStyle && (
        <>
          <span className="text-muted-foreground/50">·</span>
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${complexityStyle.bg} ${complexityStyle.text}`}
            title={`Complexity: ${complexity}${routing?.complexity_confidence ? ` (${(routing.complexity_confidence * 100).toFixed(0)}% confidence)` : ""}`}
          >
            {complexityStyle.label}
          </span>
        </>
      )}

      {/* Intent */}
      {intent && (
        <>
          <span className="text-muted-foreground/50">·</span>
          <span
            className="text-muted-foreground/80"
            title={`Intent: ${intent}${routing?.intent_confidence ? ` (${(routing.intent_confidence * 100).toFixed(0)}% confidence)` : ""}`}
          >
            {formatIntent(intent)}
          </span>
        </>
      )}

      <span className="text-muted-foreground/50">·</span>

      {/* GPT-5.2 Pro comparison */}
      <span className="text-muted-foreground/80">
        vs {comparisonCost} GPT-5.2 Pro
      </span>

      {/* Savings badge */}
      {savingsPercent > 0 && (
        <span className="ml-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-400">
          -{savingsPercent.toFixed(0)}%
        </span>
      )}
    </div>
  );
}


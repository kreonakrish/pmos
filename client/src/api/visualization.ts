/* ---------------------------------------------------------------
 * PMOS — Visualization wire types
 *
 * Shape produced by the orchestrator when a deterministic Report
 * (Ext2) is matched and executed: the chart inferer attaches one
 * or more `Visualization` records onto the assistant message's
 * `metadata.visualizations` array. Also surfaced on the immediate
 * POST response body via `ChatResponse.visualizations`.
 *
 * Keep this file in lock-step with the Pydantic model on the
 * backend (see services/orchestrator/.../visualization.py).
 * --------------------------------------------------------------- */

export type ChartType = 'bar' | 'line' | 'pie' | 'area' | 'table';

export interface Visualization {
  /** Initial chart type recommended by the inferer. */
  type: ChartType;
  /** Short human title shown in the card header. */
  title: string;
  /** Optional one-liner explaining what is being plotted. */
  description?: string | null;
  /** Column name used for the x axis / category / pie label. */
  x_field: string;
  /** One or more column names to plot as numeric series. */
  y_fields: string[];
  /** Tabular data — one row per category, columns include x_field + y_fields. */
  data: Array<Record<string, string | number | boolean | null>>;
  /** Free-form hint, e.g. "date-x → line". */
  inferred_from?: string;
  /**
   * If the inferer downsampled to <=200 rows, this carries the original
   * row count so the UI can show "Showing 200 of N rows".
   */
  truncated_from?: number | null;
}

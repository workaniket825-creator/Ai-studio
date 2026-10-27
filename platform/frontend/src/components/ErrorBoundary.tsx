import { Component, ErrorInfo, ReactNode } from "react";
import { NonIdealState, Button } from "@blueprintjs/core";

/** Catches render errors in any screen and shows a friendly recovery panel
 *  instead of a blank white screen. Reset returns to a clean render. */
export class ErrorBoundary extends Component<
  { children: ReactNode; onReset?: () => void },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    // surfaced in the console for support; no telemetry sent anywhere
    console.error("Screen error:", error, info.componentStack);
  }
  reset = () => { this.setState({ error: null }); this.props.onReset?.(); };

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40 }}>
          <NonIdealState
            icon="error"
            title="Something went wrong on this screen"
            description={this.state.error.message || "An unexpected error occurred."}
            action={<Button intent="primary" icon="refresh" text="Reload this screen" onClick={this.reset} />}
          />
        </div>
      );
    }
    return this.props.children;
  }
}

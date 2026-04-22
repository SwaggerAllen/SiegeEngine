declare module 'unidiff' {
  interface FormatOptions {
    aname?: string;
    bname?: string;
    context?: number;
    pre_context?: number;
    post_context?: number;
  }

  export function diffAsText(
    a: string | string[],
    b: string | string[],
    opt?: FormatOptions,
  ): string;
}

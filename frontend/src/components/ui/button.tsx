import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium tracking-[-0.01em] transition-all duration-300 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none active:scale-[0.985] [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-[0_12px_30px_hsl(var(--primary)/0.25)] hover:-translate-y-0.5 hover:bg-primary/92 hover:shadow-[0_18px_40px_hsl(var(--primary)/0.28)]",
        secondary:
          "border border-white/10 bg-secondary/88 text-secondary-foreground shadow-[0_8px_24px_rgba(15,23,42,0.08)] hover:-translate-y-0.5 hover:bg-secondary/100 dark:border-white/10",
        outline:
          "border border-border/70 bg-background/70 shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] backdrop-blur-md hover:-translate-y-0.5 hover:bg-background/90 hover:text-foreground",
        ghost:
          "text-muted-foreground hover:bg-background/70 hover:text-foreground",
        destructive:
          "bg-destructive text-destructive-foreground shadow-[0_12px_30px_hsl(var(--destructive)/0.22)] hover:-translate-y-0.5 hover:bg-destructive/92",
        glass:
          "border border-white/20 bg-white/75 text-foreground shadow-[0_14px_34px_rgba(15,23,42,0.10)] backdrop-blur-xl hover:-translate-y-0.5 hover:bg-white/85 dark:border-white/10 dark:bg-white/[0.06] dark:hover:bg-white/[0.10]",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 rounded-lg px-3 text-xs",
        lg: "h-11 rounded-2xl px-8 text-base",
        icon: "h-10 w-10 rounded-xl",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export type ButtonVariant =
  | "default"
  | "secondary"
  | "outline"
  | "ghost"
  | "destructive"
  | "glass";

export type ButtonSize = "default" | "sm" | "lg" | "icon";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };

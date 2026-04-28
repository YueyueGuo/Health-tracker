import { motion } from "framer-motion";
import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
}

const cardVariants = {
  hidden: { opacity: 0, y: 20 },
  show: {
    opacity: 1,
    y: 0,
    transition: { type: "spring" as const, stiffness: 300, damping: 24 },
  },
};

export function Card({ children, className = "" }: CardProps) {
  return (
    <motion.div
      variants={cardVariants}
      className={`bg-card border border-cardBorder rounded-2xl p-5 shadow-sm ${className}`}
    >
      {children}
    </motion.div>
  );
}

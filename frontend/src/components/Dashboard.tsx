import { motion } from "framer-motion";
import { MorningStatusCard } from "./dashboard/MorningStatusCard";
import { RecommendationCardV2 } from "./dashboard/RecommendationCardV2";
import { YesterdayActivityCard } from "./dashboard/YesterdayActivityCard";

const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
};

export default function Dashboard() {
  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="show"
      className="flex flex-col gap-4"
    >
      <MorningStatusCard />
      <RecommendationCardV2 />
      <YesterdayActivityCard />
    </motion.div>
  );
}

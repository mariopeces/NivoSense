import Map from "./components/Map";
import Sidebar from "./components/Sidebar";

export default function App() {
  return (
    <div className="flex h-screen w-screen bg-slate-900 text-slate-100">
      <Sidebar />
      <div className="flex-1 relative">
        <Map />
      </div>
    </div>
  );
}
